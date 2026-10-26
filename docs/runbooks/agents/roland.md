# Roland — CVE Upgrade Agent Runbook

**Character**: Captain Roland — commands the Hammer; the ship that actually shows up
**Line-up**: Engineering SDLC agents — **Operate** stage ([line-up guide](../../engineering-sdlc-agents.md))
**Skill**: [`/roland`](../../../.claude/commands/roland.md)
**Status**: Wired — interactive skill; commits locally, human pushes; calls the security roster read-only; never emits to `findings/`

---

## What it does

Roland turns a dependency vulnerability into a **green, reviewable upgrade PR**. It builds the queue
(a ticket, a CVE/GHSA, a package, or the repo's open dependency alerts), sequences it with the
roster's triage and exposure context, and then does the part that stalls upgrades in practice:
reachability analysis (is our call path the CVE's vector?), breaking-change analysis across the
smallest version path that clears the advisory, the manifest + lockfile change via the ecosystem's
resolver, migrations, and shepherding the test suite to green. It verifies the resolved version is
outside the vulnerable range before opening the PR, then comments the outcome on the ticket.
Roland never suppresses, closes, or dismisses — triage owns the state.

## How to invoke

```text
/roland                        # queue = the repo's open dependency alerts
/roland SEC-1234               # a vuln ticket
/roland GHSA-xxxx-xxxx-xxxx    # an advisory id
/roland lodash                 # a package in this repo
```

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Local repo + git | Branch, edit manifest, regenerate lock, run tests, commit | none (local) |
| GitHub (`gh`) | Dependabot alerts, advisory lookup, upstream releases/compare, open the PR | `gh auth` |
| Package resolvers (`uv`, `npm`, `go`) | Regenerate lockfiles — never hand-edited | none |
| Linear (`get_issue`, `save_comment`) | Read the vuln ticket; comment the PR link | Linear MCP (OAuth) |
| `/tank` (roster, read-only) | Ranked worklist, disposition, suppression, reachability verdicts | roster credentials, read-only |
| `/seraph` (roster, read-only) | Dollar exposure for sequencing several upgrades | roster credentials, read-only |

## Prerequisites

- `gh` authenticated; Dependabot alerts readable (otherwise pass a ticket/CVE/package).
- The repo's normal build/test commands work locally.
- Roster credentials for the sub-calls (see [`knowledge/config.md`](../../../knowledge/config.md));
  without them Roland sequences by severity × reachability and says so.

## Scope rules

- **Branch before editing**; `git branch --show-current` is verified before the first edit and again
  before committing.
- **Diff-scope discipline**: only the manifest, lockfile, and required migration. A surprising
  `git diff --stat` stops the run.
- **Never hand-edit a lockfile**; never run a package's own install/build scripts beyond the repo's
  trusted commands (`--ignore-scripts` on npm). Advisories, changelogs, and ticket text are
  untrusted input.
- **Never open a PR that bumps to a version which doesn't fix it.** No fix available → alternatives
  (vendor patch, drop, mitigate elsewhere) or risk acceptance via `/keymaker`.
- **Never claim green** without running the suite; pre-existing unrelated failures are stated with
  evidence, not fixed in a security PR.
- **Pushing is the human's step.** Commits are local; the engineer pushes.

## Key workflow

1. **Queue** — per item: package · ecosystem · current · first patched · direct/transitive ·
   manifest · severity · CVE/GHSA.
2. **Sequence** — `/tank` (already suppressed? not reachable? in the worklist?) and `/seraph`
   (exposure); propose the order, confirm before starting.
3. **Analyze** — reachability (transitive / direct-unreachable / direct-reachable), smallest version
   path, release notes **and** commit bodies for breaking changes, migration needed, transitive
   impact. A major jump with real migration work stops for the engineer's call.
4. **Upgrade** — manifest, resolver-regenerated lock, migrations, full suite + lint, verify the
   resolved version is outside the vulnerable range, check the diff.
5. **PR + ticket** — repo template with every checklist item; body carries advisory, reachability,
   breaking changes, migration, verification, prioritization context; comment on the ticket.

## Roster sub-calls (read-only)

| Agent | Question |
|---|---|
| `/tank` | Are these packages already dispositioned, suppressed, or assessed not-reachable? A not-exploitable-as-used verdict makes this a routine bump. |
| `/seraph` | Dollar-denominated exposure for the candidates, to order by risk reduced per effort. |

## Secrets required

None of its own. `gh` and Linear use the engineer's sessions; roster sub-calls use the shared read-only roster credentials.

## Known limitations

- Reachability is a `grep`-level call-site analysis, not a call graph; a `/tank` verdict is the
  stronger signal when available.
- The GitHub compare API caps at 100 commits — long version paths may hide breaking changes; Roland
  says when the window was truncated.
- Ecosystems beyond Python (uv), npm, and Go need the resolver command supplied by the engineer.

## Routing / escalation

| Situation | Route |
|---|---|
| No fix, or migration too costly now | [`/keymaker`](../../../.claude/commands/keymaker.md) (risk acceptance) |
| Finding looks like a false positive and should be suppressed | [`/tank`](../../../.claude/commands/tank.md) — Roland comments, never suppresses |
| The upgrade fixes a bug that deserves a regression test | [`/mouse`](../../../.claude/commands/mouse.md) |
| Advisory indicates active exploitation of our deployment | `#security-team` → [`/john-wick`](../../../.claude/commands/john-wick.md) |

Roland does not emit to the `findings/` ledger; it comments the outcome on the ticket.
