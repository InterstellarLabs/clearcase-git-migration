# ClearCase to GitHub Enterprise Cloud (GHEC)

## Migration approach

Migrating from IBM Rational ClearCase—Base ClearCase or UCM—to GitHub
Enterprise Cloud (GHEC) is a two-stage process:

1. **ClearCase to Git:** extract source and the required history from ClearCase
   VOBs, then reconstruct it in one or more local Git repositories.
2. **Git to GHEC:** validate the converted repositories, create and configure
   their GHEC destinations, and push the repositories to GitHub.

GitHub does not provide a native ClearCase importer through GitHub Enterprise
Importer. The migration therefore needs a ClearCase-aware extraction and
conversion step before repositories can be onboarded to GHEC.

> **Recommended default:** migrate the current source plus selected release
> labels or UCM baselines. Keep the original ClearCase environment read-only
> for deep historical lookups when complete history is not required in Git.
> This usually provides a more predictable migration than attempting to
> reconstruct every file-level operation across a long-lived VOB.

The final strategy should be confirmed during discovery. Full history may be
appropriate for smaller VOBs or when granular historical traceability is a
requirement.

## Migration principles

- **Choose repository boundaries deliberately.** A VOB is not automatically a
  good Git repository boundary. Separate independently owned projects or
  services where practical, and account for shared code and dependencies.
- **Define what “history” means.** A current snapshot, selected release
  checkpoints, and full version history have different cost, fidelity, and
  validation requirements.
- **Preserve traceability.** Map ClearCase users to Git identities and retain
  relevant version IDs, labels, baseline names, attributes, and ticket
  references where the chosen converter supports them.
- **Treat conversion as a data migration.** Pilot representative repositories,
  compare source content, and validate branches and tags before production
  cutover.
- **Separate source conversion from platform onboarding.** ClearCase-to-Git
  conversion and Git-to-GHEC configuration are related but distinct
  workstreams.

## Architecture mapping

| ClearCase concept | Git / GHEC equivalent | Migration guidance |
| --- | --- | --- |
| VOBs and UCM components | Git repositories | Define repository boundaries by project, service, ownership, and dependency—not only by existing VOB layout. |
| UCM streams and ClearCase branches | Git branches | Map active integration and release lines to suitable Git branches. Validate stream and branch ancestry; the mapping may not be one-to-one. |
| Labels and UCM baselines | Git tags and commits | Recreate selected checkpoints in chronological order. Use annotated tags for release labels where appropriate. |
| File versions and check-ins | Git commits and file history | Git records repository-wide snapshots. A conversion tool may group related ClearCase events into commits, so the resulting history is not necessarily identical to the original event model. |
| Large binaries and derived objects | Git LFS, GitHub Packages, or external artifact storage | Exclude reproducible build outputs. Identify assets that must be versioned and choose an approved storage path before migration. |
| Triggers, config specs, and build rules | GitHub Actions and repository rulesets | Inventory existing behavior and replace it with explicit CI checks, workflows, and governance rules. |
| ClearQuest records | GitHub Issues or an external tracker | Decide whether to migrate records or retain the existing tracker. Preserve ticket IDs in commit messages or other agreed metadata. |

## Conversion strategy

Select the history model before estimating or building migration tooling.

| Strategy | Suitable when | Typical method | Trade-offs |
| --- | --- | --- | --- |
| **Current snapshot** | The priority is a fast, low-risk source cutover | Export the approved ClearCase view into a clean Git repository and create an initial commit | Fastest option, but does not recreate prior source history. Keep ClearCase available read-only if historical lookup is needed. |
| **Selected labels or baselines** | Important releases and milestones must be represented | Export approved labels or baselines chronologically; create a commit and tag for each checkpoint | Often a practical balance of useful history and migration effort. Unlabeled intermediate changes may be omitted. |
| **Full history** | Fine-grained history is a business or compliance requirement and the VOB is suitable for conversion | Use ClearCase-aware tooling, such as `clearexport_ccase` with a reviewed conversion workflow, to transform history into Git commits | Higher complexity and runtime. Branch topology, event grouping, metadata, and content fidelity require careful validation. |

For large or long-lived VOBs, a label- or baseline-centered migration is often
more predictable than exporting every file revision. ClearCase and Git have
different history models: ClearCase tracks individual element versions and
views are governed by config specs, while Git commits capture repository-wide
snapshots. The conversion must make explicit decisions about how to represent
that history.

### Ignoring local and build files

| Goal | Git approach | ClearCase equivalent |
| --- | --- | --- |
| Keep local/build files out of source control | Add patterns to `.gitignore` so `git add .` skips them. | **Nothing needed.** Files that are not added stay *view-private* until someone runs `mkelem`. |
| Prevent accidental check-ins of specific file types | `.gitignore` stops files from being staged. | A **pre-op trigger on `mkelem`** runs a script that rejects specific extensions or names. |

Migration implications:

- Inventory existing triggers (`cleartool lstype -kind trtype`) and translate
  them into repository rules, push protection, and CI checks.
- Triggers only stop *new* elements. Artifacts added before a trigger existed
  can still be in the VOB and its labels; decide per VOB whether to exclude
  them from the converted history.
- Git needs an explicit `.gitignore` after cutover because the view-private
  safety net disappears. Derive it from the trigger's deny-list.
- `cc2gh.py` supports this with `--ignore`, `--ignore-from-clearcase`, and a
  generated `.gitignore`.

## Delivery phases

### 1. Discover and inventory

- Identify Base ClearCase versus UCM, VOBs, components, views, streams,
  branches, labels, baselines, triggers, and config specs.
- Record repository candidates, owners, dependencies, active development
  lines, source size, and growth where available.
- Identify large files and binary or generated content. GitHub imposes file and
  push limits; confirm current GHEC limits and any organization-specific
  policies during planning.
- Agree on the history window, repository boundaries, downtime tolerance, and
  retention requirements for the legacy environment.
- Create an author mapping from ClearCase logins to Git names and email
  addresses, and confirm how identities will map to GHEC accounts, including
  Enterprise Managed Users (EMU) if applicable.

### 2. Select and prove the conversion method

- Choose snapshot, selected-label/baseline, or full-history conversion for each
  repository.
- Select representative pilot VOBs, including cases with branches, renames,
  deletions, shared components, and binary content.
- Confirm how the conversion will represent branch ancestry, timestamps,
  labels, user identities, and any required ClearCase metadata.
- For full-history conversions, assess available ClearCase export tooling and
  validate its behavior before scaling up.
- Where possible, run extraction on a host with fast local storage and
  efficient access to the ClearCase environment. Network latency can make
  history queries and file extraction a significant bottleneck.

### 3. Prepare GHEC

- Establish the target enterprise, organizations, teams, identity-provider
  integration, and provisioning model.
- Define repository naming, visibility, permissions, default branches, and
  ownership.
- Plan rulesets, branch protection, secret scanning, and other security
  controls. Coordinate initial-push requirements with administrators; apply
  the intended controls before production use.
- Decide how Git LFS, packages, and other artifact storage will be provisioned
  and governed.

### 4. Convert repositories locally

- Extract the agreed snapshots or history into local Git repositories.
- Create the planned branches, commits, and tags, and apply the author mapping.
- Move required large assets to the approved storage solution. If using Git
  LFS, migrate qualifying content before the first push and verify that LFS
  objects are uploaded with the repository.
- Preserve ClearCase identifiers, labels, attributes, and ticket references in
  commit metadata, tags, or an agreed sidecar record when required.
- Record conversion logs, counts, exceptions, and the source checkpoint used.

### 5. Pilot, validate, and rehearse

- Push pilot repositories to temporary or staging GHEC repositories.
- Compare directory trees and file checksums between each selected ClearCase
  checkpoint and its corresponding Git commit or tag.
- Validate branch and tag counts, representative ancestry, author identities,
  and required metadata.
- Confirm that deleted and renamed files are represented as expected.
- Run builds and tests. Replace dependencies on dynamic views, ClearCase
  triggers, or `clearmake` with standard checkout-based workflows, such as
  GitHub Actions, where in scope.
- Rehearse the final sync and cutover sequence, including permissions,
  rulesets, LFS uploads, and rollback or recovery steps.

### 6. Cut over and stabilize

- Announce the change freeze and make the relevant ClearCase VOBs or branches
  read-only at the agreed cutover point.
- Run the final conversion or incremental sync, then push all approved
  branches, tags, and LFS objects to production GHEC repositories.
- Verify the production repositories and enable or confirm the intended
  governance controls.
- Direct developers to the new repositories and workflows; monitor builds,
  access, and migration issues during stabilization.
- Retain a read-only ClearCase archive or server snapshot when required for
  compliance or historical lookup. Set an owner and retention period.

## Discovery questions

Use these questions to define scope and produce a reliable estimate:

1. Are you using Base ClearCase, UCM, or both?
2. How many VOBs and UCM components are in scope, and how large are they?
3. Are developers using dynamic views, snapshot views, or both?
4. Is the requirement for the latest source, selected release checkpoints, or
   complete revision history?
5. Must UCM activities, baselines, labels, branch relationships, or ClearQuest
   records be preserved?
6. Are there shared VOBs, shared components, or cross-project dependencies?
7. Which files are binary, generated, or larger than GitHub's current limits?
   Which of these must remain versioned?
8. What build and CI/CD systems are used today (for example, Jenkins or
   `clearmake`)?
9. How are users and permissions managed, and will the target use EMU?
10. What is the target cutover date, acceptable downtime, and required
    read-only retention period for ClearCase?

## Workstreams and outcomes

### ClearCase to Git

Scope: source extraction, history selection, branch and tag reconstruction,
identity mapping, metadata preservation, and local validation.

**Outcome:** validated local Git repositories that represent the agreed
ClearCase content and history.

### Git to GHEC

Scope: enterprise and organization onboarding, repository creation, access
control, governance, security, CI/CD modernization, and production cutover.

**Outcome:** production GHEC repositories that are accessible, governed, and
ready for developer use.

## Suggested acceptance criteria

Agree on measurable acceptance criteria before the pilot. At minimum:

- Every in-scope repository has an approved boundary, owner, and history model.
- The selected ClearCase checkpoints match their Git counterparts by file
  inventory and content checksums, subject to documented exceptions.
- Required branches, tags, author identities, and metadata are present.
- Required large-file content is accessible from the target repositories.
- Builds and tests pass, or remaining failures are documented and accepted.
- Permissions, security controls, and repository rules are verified in GHEC.
- The cutover runbook, rollback/recovery plan, and ClearCase retention plan are
  approved.

## References

- [Git Book: Migrating to Git](https://git-scm.com/book/en/v2/Git-and-Other-Systems-Migrating-to-Git)
- [GitHub: Planning your migration to GitHub](https://docs.github.com/enterprise-cloud@latest/migrations/overview/planning-your-migration-to-github)
- [GitHub Enterprise migrations](https://github.com/enterprise/migrating-to-github)
- [ClearCase to Git migration discussion: preserving history](https://stackoverflow.com/questions/37048859/moving-from-clearcase-to-git-need-to-dump-history)
- [ClearCase to Git migration overview](https://www.releaseteam.com/clearcase-to-git-migration/)
- [ClearCase migration notes](https://therub.org/2013/07/19/clearcase-to-git/)
- [GitLab documentation: ClearCase migration](https://docs.gitlab.com/user/import/third_party_systems/clearcase/)
