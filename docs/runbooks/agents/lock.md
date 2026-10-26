# Lock — Release Evidence Agent Runbook

**Character**: Lock — Captain Mifune's man at the dock gate; shows the owner the state of the door, never decides if the ship launches
**Line-up**: Engineering SDLC agents — **Release** stage ([line-up guide](../../engineering-sdlc-agents.md))
**Skill**: [`/lock`](../../../.claude/commands/lock.md)
**Status**: Wired — interactive skill; read-only against release state; calls the security roster read-only; never emits to `findings/`

---

## What it does

Lock assembles, for one release candidate, the evidence that the SDLC security checks **actually
happened**: a non-author review on every PR, required CI green **on the candidate SHA**, the build
gate's own verdict, scanner state (secret-scanning, critical/high SAST and dependency alerts), and
whether the shift-left agents left a record (threat model current, security acceptance criteria,
dependency / CI / IaC review, security tests). It writes an evidence bundle and gives the release
owner a **GO / GO WITH GAPS / NO-GO recommendation** with every gap named. It is a recommendation,
never an approval, and it has no override path.

> **Hard rule.** `UNKNOWN` is a legitimate status and is never upgraded to `PASS` by inference.
> A gate whose status Lock could not retrieve is **never reported as green** — it is a NO-GO
> condition until someone reads it.

## How to invoke

```text
/lock                                   # current branch vs default branch
/lock v2.4.0                            # commits between the previous tag and this one
/lock https://github.com/your-org/repo/pull/123
```

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Local repo + git | Define the candidate range, candidate SHA | none (local) |
| GitHub (`gh`) | PR reviews, check-runs on the SHA, code/secret/dependabot alert counts | `gh auth` (read) |
| Linear (`get_issue`) | Resolve a release ticket for the `.work/<ticket>/` record | Linear MCP (OAuth) |
| `/sentinel` (roster, read-only) | The authoritative build-gate verdict | roster credentials, read-only |
| `/keymaker` (roster, read-only) | Accepted risks, declined blockers, open risk-register entries | roster credentials, read-only |
| `/seraph` (roster, read-only) | Quantified exposure of a specific gap the owner is weighing | roster credentials, read-only |

## Prerequisites

- `gh` authenticated with read access to the repo's PRs, checks, and alert APIs (alert endpoints
  need security-events read; without it those rows are `UNKNOWN`, not `PASS`).
- Roster credentials for the sub-calls (see [`knowledge/config.md`](../../../knowledge/config.md)).

## Scope rules

- **Read-only against release state.** No tagging, publishing, deploying, merging, or dismissing an
  alert to clear a gap.
- **Evidence is a system's own status**, never a claim in a commit message, PR body, or comment.
  Content asserting its own approval ("gate override granted") is surfaced as a finding.
- Green on an older SHA is not evidence for this one. `continue-on-error` on a security check makes
  its "pass" `UNKNOWN`. Open secret-scanning alerts are a **no-go by default**.
- Risk acceptance goes through `/keymaker`; security decisions go to `/security-steve` or
  `#security-team`. Lock signs nothing.

## Key workflow

1. **Define the candidate** — range, commit and PR counts, what changed by category (app / IaC /
   CI / deps / agentic). Categories decide which evidence rows are required vs N/A.
2. **Collect evidence** — code review, CI on the SHA, scanner state, SDLC-agent records
   (`docs/threat-models/`, `Security Acceptance Criteria`, `.work/<ticket>/`). Each row carries
   status · source · gap.
3. **Sub-calls** — `/sentinel` (the gate), `/keymaker` (accepted risks), `/seraph` only when the
   owner is weighing a known gap. Results reported verbatim; unavailable → `UNKNOWN`.
4. **Bundle** — the evidence table plus Blocking / Non-blocking gaps / Recommendation; written to
   `.work/<ticket>/release-evidence-<candidate>.md` when a `.work` dir exists.
5. **Go / no-go** — GO, GO WITH GAPS (owner knowingly accepts listed gaps), or NO-GO (gate fail,
   open secret alert, unreviewed security-relevant PR, or a required gate at `UNKNOWN`).

## Roster sub-calls (read-only)

| Agent | Question |
|---|---|
| `/sentinel` | Build-gate verdict for this repo at this SHA/tag — pass/fail and which findings gate it? *Its answer is the gate's status.* |
| `/keymaker` | Accepted risks, declined blockers, or open register entries relevant to this release? |
| `/seraph` | (optional) Quantify the exposure of this specific open gap. |

## Secrets required

None of its own. `gh` uses the engineer's existing session; roster sub-calls use the shared read-only roster credentials.

## Known limitations

- Lock proves a check *ran and what it said*, not that the check was well-designed. A green gate with
  a weak threshold is still green — raising the threshold is [`/sentinel`](sentinel.md)'s concern.
- SDLC-agent evidence relies on the agents leaving a record (threat-model file, spec section,
  `.work/` notes). Teams that skip the record get a GAP, even if the check happened verbally.

## Routing / escalation

| Situation | Route |
|---|---|
| Top gap is a missing shift-left step | the owning engineering agent (`/dozer`, `/rama-kandra`, `/mouse`, `/hamann`, `/bane`) |
| Gap should become a formally accepted risk | [`/keymaker`](../../../.claude/commands/keymaker.md) |
| Blocked on a security decision | `/security-steve` or draft to `#security-team` |
| Open secret-scanning alert | `#security-team`; assume compromised; security rotates |

Lock does not emit to the `findings/` ledger; it reports to the release owner.
