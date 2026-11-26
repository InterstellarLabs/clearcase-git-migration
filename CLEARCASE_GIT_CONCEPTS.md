# ClearCase and Git: Structure and Migration Mapping

## 1. ClearCase repository (VOB) structure

Unlike Git, which records repository-wide snapshots as commits, ClearCase
versions elements (files and directories) individually inside a Versioned
Object Base (VOB). Each element has a version tree. A view's config spec
selects versions from those trees to present a working view of the VOB.

```text
ClearCase VOB (Versioned Object Base)
└── /vobs/my_project                 (directory element)
    ├── /main/0 ── /main/1 ── /main/2 (LATEST)
    └── src/                         (directory element)
        └── app.java                 (file element)
            └── /main/0
                ├── /main/1 [label: REL_1.0]
                │   └── /dev_branch/0 ── /dev_branch/1
                │                       (selected by a development config spec)
                └── /main/2 [label: REL_2.0]
                                        (selected by a production config spec)
```

The diagram is illustrative: labels and branches are attached to ClearCase
versions, and a config spec can select versions using rules rather than
selecting a single repository-wide revision.

## 2. ClearCase-to-GitHub metadata mapping

Migrating to GitHub means translating ClearCase's element-level history and
view rules into Git's repository-wide commits, branches, and tags. These
mappings are practical approximations, not one-to-one equivalents.

```text
IBM RATIONAL CLEARCASE                     GITHUB (GIT)
══════════════════════════                 ════════════
VOB or UCM component          ───────────► Git repository
Element version (/main/1)     ───────────► File content in a commit snapshot
Branch type (brtype)          ───────────► Git branch (refs/heads/*)
Label type (lbtype)           ───────────► Git tag (refs/tags/*)
UCM baseline                  ───────────► Git commit/tag or GitHub Release
UCM stream                    ───────────► Long-lived Git branch
UCM activity / change set     ───────────► Related Git commit(s) or pull request
Check-in comment              ───────────► Commit message
Attributes / hyperlinks       ───────────► Commit trailers or external metadata
```

### Key structural translations

| ClearCase concept | GitHub equivalent | Migration strategy and caveats |
| --- | --- | --- |
| VOB / UCM component | Git repository | A large VOB containing unrelated projects may be split into multiple repositories. Account for shared code and cross-repository dependencies. |
| Element versions | Commits and file history | ClearCase checks in elements individually; Git commits capture whole-tree snapshots. A converter must decide which related ClearCase events belong together in a commit. |
| Labels (`lbtype`) | Git tags | A ClearCase label can refer to selected versions across elements. Reconstruct the complete labeled tree as a Git commit, then tag that commit. |
| UCM activities | Commits / pull requests | Activities group related changes and can inform commit grouping. The mapping depends on the activity's actual contents and workflow. |
| Config specs | Branches and dependency configuration | A config spec's selection rules do not generally translate to a branch one-to-one. If it selects content from other VOBs, consider Git submodules or package managers such as Maven, npm, or NuGet. |
| UCM baselines | Git commits/tags or GitHub Releases | Preserve the baseline's exact source state as a Git commit. Use a tag for a stable source checkpoint; a GitHub Release can additionally carry release notes and assets. |
| UCM streams / ClearCase branches | Git branches | Map active development and release lines to branches after validating ancestry and integration behavior. |
| Attributes / hyperlinks | Commit trailers or external metadata | Custom metadata has no universal native Git equivalent. Preserve required data in agreed trailers (for example, `ClearCase-Activity: ACT0012`) or a separate migration record. |
| Check-in comments | Commit messages | Retain comments where possible, and normalize or augment them only according to an agreed migration policy. |
| Triggers | GitHub Actions, rulesets, or Git hooks | Translate pre-check-in checks to required status checks, rulesets, or client-side hooks as appropriate. Post-check-in automation may become GitHub Actions workflows. |

When reconstructing history from Base ClearCase, grouping nearby check-ins by
author and time can be a heuristic, but a fixed time window (such as 5–10
minutes) can combine unrelated changes or split related changes. Prefer
available change-set, activity, ticket, and branch context, and document the
chosen grouping rules.

## 3. Common migration hurdles

### Evil twins

ClearCase can have two distinct elements with the same pathname over time,
such as when an element is removed and a new element is created at that path.
Git represents the current tree by path, so it cannot represent both as
separate simultaneous entries at the same path. Conversion must choose how to
preserve the distinction in history and record any identity loss.

### Versioned directories and empty directories

ClearCase versions directory contents independently of file contents. Git
tracks files (and symlinks), not directories as independent versioned objects.
An empty ClearCase directory therefore has no representation in a Git commit
unless a placeholder file, such as `.gitkeep`, is deliberately added.

### History size and pruning

Many years of granular file-by-file history can produce a large, complex
conversion. Decide whether to migrate all history, selected active branches
and release checkpoints, or only current source. If full history is not
required in Git, retaining the ClearCase VOB read-only can support compliance
and historical lookups while keeping the Git repository more manageable.
