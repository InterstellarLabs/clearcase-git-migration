"""Minimal stand-in for `cleartool`, backed by JSON fixtures.

Supported: lsvob -short | lshistory [-recurse] [-nco] -fmt FMT PATH | get -to OUT PATH[@@VERSION]
           | lstype -kind trtype -invob VOB -short   (trigger types, from the fixture's "triggers" list)
Format specifiers: %Nd %u %En %Vn %o %Nl %Na %c %[activity]p (UCM activity; empty for Base ClearCase).
Fixtures dir: $CC_MOCK_FIXTURES or ./fixtures next to this file.

Fixture events mirror lshistory records: op is mkelem, mkbranch, checkin or rmname. Only checkin
versions carry content. Simplification: rmname is recorded on the file element, whereas real
ClearCase records it on the parent directory version.
"""
import base64
import json
import os
import re
import sys
from pathlib import Path

FIXTURES = Path(os.environ.get("CC_MOCK_FIXTURES", Path(__file__).parent / "fixtures"))


def load_vobs():
    return {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(FIXTURES.glob("*.json"))}


def find_vob(path, vobs):
    norm = "/" + path.replace("\\", "/").strip("/") + "/"
    for name, vob in vobs.items():
        if f"/{name}/" in norm:
            return name, vob, norm.split(f"/{name}/", 1)[0] + f"/{name}"
    sys.exit(f"cleartool: Error: Unable to find VOB for path: {path}")


def fmt_attrs(attrs):
    # %Na: no parentheses or commas; string values quoted, numbers bare.
    return " ".join(f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}" for k, v in attrs.items())


def expand(fmt, root, v):
    values = {
        "Nd": v["date"], "u": v["user"], "En": f"{root}/{v['element']}", "Vn": v["version"],
        "o": v["op"], "Nl": " ".join(v.get("labels", [])), "Na": fmt_attrs(v.get("attrs", {})),
        "c": v.get("comment", ""), "[activity]p": v.get("activity", ""),
    }
    return re.sub(r"%(Nd|En|Vn|Nl|Na|u|o|c|\[activity\]p)", lambda m: values[m.group(1)], fmt)


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    vobs = load_vobs()
    cmd, args = argv[0], argv[1:]
    if cmd == "lsvob":
        for name in vobs:
            print(f"/vobs/{name}")
    elif cmd == "lshistory":
        fmt = args[args.index("-fmt") + 1]
        path = args[-1]
        _, vob, root = find_vob(path, vobs)
        for v in sorted(vob["versions"], key=lambda x: x["date"], reverse=True):
            print(expand(fmt, root, v))
    elif cmd == "lstype":
        if args[args.index("-kind") + 1] != "trtype" or "-short" not in args:
            sys.exit("cleartool: Error: mock supports only 'lstype -kind trtype -invob VOB -short'")
        _, vob, _ = find_vob(args[args.index("-invob") + 1], vobs)
        for trigger in vob.get("triggers", []):
            print(trigger["name"])
    elif cmd == "get":
        out = Path(args[args.index("-to") + 1])
        element_path, _, version = args[-1].partition("@@")
        _, vob, root = find_vob(element_path, vobs)
        rel = element_path.replace("\\", "/")[len(root) + 1:]
        if out.exists():
            sys.exit(f'cleartool: Error: Output file "{out}" already exists.')
        if not version:
            # no version given: the view's selection, modeled as the latest /main version
            mains = [v for v in vob["versions"] if v["element"] == rel and re.fullmatch(r"/main/\d+", v["version"])
                     and v["op"] == "checkin"]
            if mains:
                version = max(mains, key=lambda v: int(v["version"].rsplit("/", 1)[1]))["version"]
        for v in vob["versions"]:
            if v["element"] == rel and v["version"] == version and "content" in v:
                out.write_bytes(v["content"].encode("utf-8"))
                return
            if v["element"] == rel and v["version"] == version and "content_base64" in v:
                out.write_bytes(base64.b64decode(v["content_base64"], validate=True))
                return
        sys.exit(f"cleartool: Error: Version not found: {args[-1]}")
    else:
        sys.exit(f"cleartool: Error: mock does not support '{cmd}'")


if __name__ == "__main__":
    main(sys.argv[1:])
