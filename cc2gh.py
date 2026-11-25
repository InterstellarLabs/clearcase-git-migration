"""Convert a base-ClearCase VOB's history into a Git repository (optionally pushed to GitHub).

Examples (mock data, no ClearCase needed):
  python cc2gh.py --mock --vob-root /vobs/sample_app --out out
  python cc2gh.py --mock --vob-root /vobs/sample_app --out out --push OWNER/sample_app --releases

Real ClearCase: drop --mock (or pass --cleartool "path\\to\\cleartool.exe"), run from a machine/view
that can see the VOB.

Mapping: version -> commit (grouped by branch+user+comment within 5 min), branch -> branch,
label -> annotated tag, attributes/version ids -> commit trailers, plus a full JSON sidecar
committed on the `clearcase-metadata` branch. Times are treated as UTC. Text files only.

Ignoring files: ClearCase has no .gitignore. Never-added files stay view-private, and an mkelem
pre-op trigger (typically reading a deny-list element) blocks artifact types. Elements that predate
the trigger can still sit in a VOB, so use --ignore / --ignore-from-clearcase to leave them out of
the Git history; a .gitignore with the same patterns is committed on the tip of main so they stay
out afterwards. VOB trigger types are listed and recorded in the metadata sidecar.
"""
import argparse
import csv
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

FMT = "%Nd|%u|%En|%Vn|%o|%Nl|%Na|%[activity]p|%c@@END@@"
GROUP_WINDOW = timedelta(minutes=5)
META_BRANCH = "clearcase-metadata"


@dataclass
class Rec:
    when: datetime
    user: str
    en: str
    rel: str
    ver: str
    op: str
    labels: list
    attrs: dict
    activity: str
    comment: str

    @property
    def branch(self):
        parts = self.ver.strip("/").split("/")[:-1]
        return parts[-1] if parts else "main"


@dataclass
class Commit:
    branch: str
    user: str
    comment: str
    recs: list = field(default_factory=list)
    sha: str = ""

    @property
    def start(self):
        return self.recs[0].when

    @property
    def end(self):
        return self.recs[-1].when


def run(cmd, input=None, env=None, check=True, binary=False):
    # Bytes in/out: text mode would turn "\n" into "\r\n" on Windows and corrupt git input.
    data = input.encode("utf-8") if isinstance(input, str) else input
    p = subprocess.run(cmd, input=data, env=env, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f"{' '.join(map(str, cmd))} failed: {p.stderr.decode('utf-8', 'replace').strip()}")
    if not binary:
        p.stdout = p.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        p.stderr = p.stderr.decode("utf-8", "replace").replace("\r\n", "\n")
    return p


def git(repo, *args, **kw):
    cmd = ["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
           "-C", str(repo), *args]
    return run(cmd, **kw).stdout.strip()


def parse_attrs(text):
    # %Na output: name="string" or name=number, space separated.
    return {k: v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|[^\s",]+)', text)}


def fetch_history(ct, vob_root):
    out = run([*ct, "lshistory", "-recurse", "-nco", "-fmt", FMT, vob_root]).stdout
    root = vob_root.replace("\\", "/").rstrip("/") + "/"
    recs = []
    for chunk in out.split("@@END@@"):
        chunk = chunk.lstrip("\r\n")
        if not chunk.strip():
            continue
        date, user, en, ver, op, labels, attrs, activity, comment = chunk.split("|", 8)
        norm = en.replace("\\", "/")
        if op not in ("checkin", "rmname") or not norm.startswith(root):
            continue
        recs.append(Rec(
            when=datetime.strptime(date, "%Y%m%d.%H%M%S"), user=user, en=en, rel=norm[len(root):], ver=ver,
            op=op, labels=re.sub(r"[(),]", " ", labels).split(), attrs=parse_attrs(attrs),
            activity=activity.strip(), comment=comment.strip()))
    return sorted(recs, key=lambda r: (r.when, r.rel))


def group_commits(recs):
    open_groups, commits = {}, []
    for r in recs:
        key = (r.branch, r.user, r.activity or r.comment)
        g = open_groups.get(key)
        if g is None or r.when - g.end > GROUP_WINDOW:
            g = open_groups[key] = Commit(r.branch, r.user, r.comment)
            commits.append(g)
        g.recs.append(r)
    return sorted(commits, key=lambda c: c.start)


def load_users(path):
    if not path or not Path(path).exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {row["login"]: row for row in csv.DictReader(f)}


def identity(users, login):
    u = users.get(login)
    return (u["name"], u["email"]) if u else (login, f"{login}@users.noreply.invalid")


def tag_name(label):
    return re.sub(r"[^\w.\-]", "_", label)


def message(c):
    lines = [c.comment or "(no comment)", ""]
    if c.recs[0].activity:
        lines.append(f"ClearCase-Activity: {c.recs[0].activity}")
    for r in c.recs:
        lines.append(f"ClearCase-Version: {r.rel}@@{r.ver}" + (" (removed)" if r.op == "rmname" else ""))
        for k, v in r.attrs.items():
            lines.append(f"ClearCase-Attribute: {r.rel}: {k}={v}")
        for lb in r.labels:
            lines.append(f"ClearCase-Label: {lb}")
    return "\n".join(lines) + "\n"


def git_commit(repo, msg, when, name, email, allow_empty=True):
    stamp = when.strftime("%Y-%m-%d %H:%M:%S +0000")
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": stamp,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": stamp}
    git(repo, "commit", "-q", *(["--allow-empty"] if allow_empty else []), "-F", "-", input=msg, env=env)
    return git(repo, "rev-parse", "HEAD")


def build_repo(ct, vob_root, repo, commits, users, tmp):
    git(repo.parent, "init", "-q", "-b", "main", str(repo))
    seen = set()
    for i, c in enumerate(commits):
        if c.branch not in seen:
            seen.add(c.branch)
            if i == 0:
                pass
            elif "main" in seen - {c.branch}:
                git(repo, "checkout", "-q", "-B", c.branch, "main")
            else:
                git(repo, "checkout", "-q", "--orphan", c.branch)
        else:
            git(repo, "checkout", "-q", c.branch)
        for r in c.recs:
            dest = repo / r.rel
            if r.op == "rmname":
                git(repo, "rm", "-q", "--ignore-unmatch", r.rel)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = Path(tmp) / f"v{i}_{len(r.rel)}_{abs(hash((r.rel, r.ver)))}"
            run([*ct, "get", "-to", str(part), f"{r.en}@@{r.ver}"])
            shutil.move(str(part), dest)
            git(repo, "add", "--", r.rel)
        name, email = identity(users, c.user)
        c.sha = git_commit(repo, message(c), c.start, name, email)
    git(repo, "checkout", "-q", "main")


def create_tags(repo, commits, users):
    tags = {}
    for c in commits:
        for r in c.recs:
            for lb in r.labels:
                tags[lb] = c
    for lb, c in tags.items():
        name, email = identity(users, c.user)
        stamp = c.end.strftime("%Y-%m-%d %H:%M:%S +0000")
        env = {**os.environ, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": stamp}
        git(repo, "tag", "-a", tag_name(lb), c.sha, "-m", f"ClearCase label {lb}", env=env)
    return tags


def split_ignored(recs, patterns):
    kept, skipped = [], []
    for r in recs:
        hit = next((p for p in patterns if is_ignored(r.rel, p)), None)
        (skipped if hit else kept).append((r, hit) if hit else r)
    return kept, skipped


def is_ignored(rel, pattern):
    if pattern.endswith("/"):
        return rel.startswith(pattern) or f"/{pattern}" in f"/{rel}"
    return fnmatch.fnmatchcase(rel.rsplit("/", 1)[-1], pattern) or fnmatch.fnmatchcase(rel, pattern)


def parse_patterns(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def load_ignore_patterns(ct, cli_patterns, cc_path, tmp):
    """Patterns from --ignore plus a deny-list element (as read by the mkelem pre-op trigger)."""
    patterns = list(cli_patterns)
    if cc_path:
        part = Path(tmp) / "ignore_list"
        run([*ct, "get", "-to", str(part), cc_path])
        patterns += parse_patterns(part.read_text("utf-8"))
    return list(dict.fromkeys(patterns))


def list_triggers(ct, vob_root):
    p = run([*ct, "lstype", "-kind", "trtype", "-invob", vob_root, "-short"], check=False)
    return p.stdout.split() if p.returncode == 0 else []


def write_gitignore(repo, patterns, when):
    git(repo, "checkout", "-q", "main")
    (repo / ".gitignore").write_text(
        "# Mirrors the ClearCase mkelem pre-op trigger deny-list. ClearCase needs no ignore file:\n"
        "# files that are never added with mkelem stay view-private.\n" + "\n".join(patterns) + "\n",
        encoding="utf-8", newline="\n")
    git(repo, "add", "--", ".gitignore")
    git_commit(repo, "Add .gitignore mirroring ClearCase mkelem deny-list\n", when + timedelta(minutes=1),
               "cc2gh", "cc2gh@users.noreply.invalid")


def write_metadata(repo, vob_root, commits, users, ignored=(), triggers=()):
    meta = {
        "vob": vob_root,
        "triggers": list(triggers),
        "ignored": [{"path": r.rel, "version": r.ver, "op": r.op, "pattern": p} for r, p in ignored],
        "commits": [{
            "sha": c.sha, "branch": c.branch, "user": c.user, "comment": c.comment,
            "activity": c.recs[0].activity,
            "versions": [{"path": r.rel, "version": r.ver, "op": r.op, "date": r.when.isoformat(),
                          "labels": r.labels, "attributes": r.attrs} for r in c.recs],
        } for c in commits],
    }
    text = json.dumps(meta, indent=2) + "\n"
    blob = git(repo, "hash-object", "-w", "--stdin", input=text)
    tree = git(repo, "mktree", input=f"100644 blob {blob}\tclearcase-metadata.json\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "cc2gh", "GIT_AUTHOR_EMAIL": "cc2gh@users.noreply.invalid",
           "GIT_COMMITTER_NAME": "cc2gh", "GIT_COMMITTER_EMAIL": "cc2gh@users.noreply.invalid"}
    sha = git(repo, "commit-tree", tree, "-m", "ClearCase metadata export", env=env)
    git(repo, "update-ref", f"refs/heads/{META_BRANCH}", sha)
    return text


def verify(ct, vob_root, repo, tmp, patterns=()):
    recs, _ = split_ignored(fetch_history(ct, vob_root), patterns)
    problems = []
    log = git(repo, "log", "--all", "--format=%B")
    n_trailers = sum(1 for ln in log.splitlines() if ln.startswith("ClearCase-Version: "))
    if n_trailers != len(recs):
        problems.append(f"version count: ClearCase={len(recs)} git={n_trailers}")
    latest = {}
    for r in recs:
        latest[(r.branch, r.rel)] = r
    for (branch, rel), r in latest.items():
        spec = f"{branch}:{rel}"
        exists = run(["git", "-C", str(repo), "cat-file", "-e", spec], check=False).returncode == 0
        if r.op == "rmname":
            if exists:
                problems.append(f"{spec} should be removed")
            continue
        if not exists:
            problems.append(f"{spec} missing")
            continue
        part = Path(tmp) / f"verify_{abs(hash(spec))}"
        run([*ct, "get", "-to", str(part), f"{r.en}@@{r.ver}"])
        got = run(["git", "-C", str(repo), "show", spec], binary=True).stdout
        if got != part.read_bytes():
            problems.append(f"{spec} content differs from {r.ver}")
    tags = set(git(repo, "tag", "--list").split())
    for lb in {lb for r in recs for lb in r.labels}:
        if tag_name(lb) not in tags:
            problems.append(f"label {lb} has no tag")
    return problems


def push(repo, slug, tags, releases):
    exists = run(["gh", "repo", "view", slug], check=False).returncode == 0
    if not exists:
        run(["gh", "repo", "create", slug, "--private"])
    remote = f"https://github.com/{slug}.git"
    run(["git", "-C", str(repo), "remote", "remove", "origin"], check=False)
    git(repo, "remote", "add", "origin", remote)
    git(repo, "push", "-q", "origin", "--all")
    git(repo, "push", "-q", "origin", "--tags")
    if releases:
        for lb in tags:
            if run(["gh", "release", "view", tag_name(lb), "-R", slug], check=False).returncode:
                run(["gh", "release", "create", tag_name(lb), "-R", slug, "--verify-tag",
                     "--title", f"ClearCase label {lb}", "--notes", f"Migrated from ClearCase label `{lb}`."])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vob-root", required=True, help="e.g. /vobs/sample_app (path visible to cleartool)")
    ap.add_argument("--out", required=True, help="directory that will contain the new git repo")
    ap.add_argument("--users", default="users.csv", help="CSV: login,name,email")
    ap.add_argument("--cleartool", default="cleartool")
    ap.add_argument("--mock", action="store_true", help="use mock_cleartool.py and ./fixtures")
    ap.add_argument("--push", metavar="OWNER/REPO", help="create (private) GitHub repo and push")
    ap.add_argument("--releases", action="store_true", help="with --push, create a GitHub release per label")
    ap.add_argument("--ignore", action="append", default=[], metavar="PATTERN",
                    help="skip matching elements (glob on name or path; trailing / = directory); repeatable")
    ap.add_argument("--ignore-from-clearcase", metavar="PATH",
                    help="element holding the mkelem trigger deny-list (one glob per line), e.g. "
                         "/vobs/build_common/triggers/mkelem_denylist.txt")
    ap.add_argument("--no-gitignore", action="store_true",
                    help="do not commit a .gitignore built from the ignore patterns")
    a = ap.parse_args()

    ct = [sys.executable, str(Path(__file__).with_name("mock_cleartool.py"))] if a.mock else shlex.split(a.cleartool)
    repo = Path(a.out).resolve() / Path(a.vob_root.replace("\\", "/")).name
    if repo.exists():
        sys.exit(f"{repo} already exists; remove it first")
    repo.parent.mkdir(parents=True, exist_ok=True)

    users = load_users(a.users)
    with tempfile.TemporaryDirectory() as tmp:
        patterns = load_ignore_patterns(ct, a.ignore, a.ignore_from_clearcase, tmp)
        all_recs = fetch_history(ct, a.vob_root)
        recs, ignored = split_ignored(all_recs, patterns)
        if not recs:
            sys.exit("no history found")
        commits = group_commits(recs)
        build_repo(ct, a.vob_root, repo, commits, users, tmp)
        tags = create_tags(repo, commits, users)
        triggers = list_triggers(ct, a.vob_root)
        write_metadata(repo, a.vob_root, commits, users, ignored, triggers)
        if patterns and not a.no_gitignore:
            write_gitignore(repo, patterns, max(c.end for c in commits))
        problems = verify(ct, a.vob_root, repo, tmp, patterns)
    print(f"{repo}: {len(recs)} versions -> {len(commits)} commits, "
          f"{len({c.branch for c in commits})} branches, {len(tags)} tags")
    if ignored:
        print(f"ignored {len(ignored)} versions of {len({r.rel for r, _ in ignored})} elements:")
        for path in sorted({(r.rel, p) for r, p in ignored}):
            print(f"  {path[0]}  (matches {path[1]})")
    if triggers:
        print(f"ClearCase triggers in VOB (rebuild as repository rules/CI): {', '.join(triggers)}")
    if problems:
        print("VERIFY FAILED:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("verify OK")
    if a.push:
        push(repo, a.push, tags, a.releases)
        print(f"pushed to https://github.com/{a.push}")


if __name__ == "__main__":
    main()
