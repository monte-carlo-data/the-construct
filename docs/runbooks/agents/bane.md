# Bane — CI/CD Hardening Agent Runbook

**Character**: Bane from *The Matrix Reloaded* — the crew member Smith escaped into the real world through
**Domain**: CISSP Domain 8 — Software Development Security (OWASP SAMM Implementation / Secure Deployment — pipeline security)
**SDLC stage**: Build
**Skill**: [`/bane`](../../../.claude/commands/bane.md) · line-up: [Engineering SDLC agents](../../engineering-sdlc-agents.md)
**Status**: Prompt-defined skill; reports to the engineer, never emits to `findings/`; drafts to Slack on a leaked credential

---

## What it does

Bane reviews and hardens the **CI/CD workflows on the engineer's branch before merge**. CI is the
softest path to a signing key, a cloud role, and every repo in the org, and it is reviewed less
carefully than application code. Bane checks each changed workflow for:

- **Trigger safety** — `pull_request_target` executing fork code, privileged `workflow_run`,
  anyone-can-trigger events without author gating
- **Token permissions** — missing `permissions:` block, `write-all`, writes not scoped per job
- **Action pinning** — third-party actions on mutable tags instead of a full commit SHA
- **Script injection** — `${{ github.event.* }}` interpolated into `run:` or `github-script`
- **Secrets handling** — broad `secrets: inherit`, secrets reachable by fork code, static cloud
  keys where OIDC (with a repo-and-ref-scoped `sub`) should be used
- **Hygiene** — self-hosted runners on fork-able repos, cache poisoning, secrets in artifacts,
  `continue-on-error` on a gate, `persist-credentials` before untrusted steps

Every finding ships with a **concrete diff**. Mechanical fixes (permissions blocks, SHA pins,
`env:` refactors) are offered and applied in-branch; architectural restructures wait for an
explicit go-ahead. The report always carries a **posture line** — pinned actions, explicit
permissions, OIDC — even when clean.

---

## How to invoke

```text
/bane                                   # review the branch's changed workflows
/bane .github/workflows/release.yml     # review one workflow
/bane                                   # no branch changes: offers a labeled full-repo baseline audit
```

`.circleci/config.yml` and `.gitlab-ci.yml` are in the diff scope; the check tables are
GitHub-Actions-specific.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Local git | Workflow diff vs the merge-base; branch check before editing | Filesystem |
| GitHub API | Resolve a tag to its commit SHA for pinning | `gh` CLI auth |
| Security roster (`/architect`) | Read-only review of complex/high-risk workflow changes | Engineer's session |
| Slack MCP | **Draft** a leaked-credential alert to `#security-team` | `mcp__slack__slack_send_message_draft` |

**Prerequisites**: a feature branch with a merge-base against `origin/main`; `gh` authenticated;
the repo's own pinning convention if stricter than "first-party actions may use a major tag".

---

## Scope rules

- **Call, never modify.** Roster agents are invoked read-only; the skill never edits a security
  skill, a roster runbook, `findings/HANDOFF_PROTOCOL.md`, or the `findings/` ledger.
- **Branch scope only.** Org-level pipeline monitoring, branch protection, org secrets, and IAM
  trust policies stay with security — Bane recommends; the owner changes them.
- **No destructive default.** Never modifies repo/org settings or trust policies; never rotates
  or prints a credential.
- **Branch before editing; diff-scope discipline.** `git branch --show-current` is checked before
  edits and before committing; a surprising `git diff --stat` stops the run.
- **Untrusted input.** Workflow content and fork-PR metadata are attacker-controlled and never
  interpolated into a shell command — the same bug class Bane reviews for.
- **Drafts never auto-sent.** The leaked-credential alert is drafted; the engineer sends.
- **Degradation is explicit.** A skipped or unavailable `/architect` sub-call is stated, with why.

---

## Key workflow

1. **Scope** — changed workflows on the branch, or the named file; offer a labeled full-repo
   baseline when the diff is empty. Read each workflow in full.
2. **Checks** — trigger safety, token permissions, pinning, expression injection, secrets
   handling, hygiene; each finding with severity (HIGH / MEDIUM / LOW) and a diff.
3. **Sub-call** `/architect` for a new privileged trigger, cloud-credential path, release pipeline,
   or any HIGH; skipped (and said so) for routine changes.
4. **Apply** mechanical fixes with `Edit` after showing the diffs; defer architectural changes.
5. **Leaked credential** — treat as compromised, draft to `#security-team` without the value,
   never attempt rotation.
6. **Report** findings by severity, applied vs deferred, sub-call status, posture line.

---

## Roster sub-calls

| Calls | For what |
|---|---|
| [`/architect`](architect.md) | Second read on the trust model between trigger, token scope, and the steps that run untrusted code — complex or high-risk changes only (read-only) |

---

## Secrets required

None held by the skill. `gh` uses the engineer's auth. No credential value is ever read into the
output, a Slack draft, or a ticket.

---

## Known limitations

- Reviews workflow files, not the runner fleet, environment protection rules, or branch-protection
  state — those are recommended, not inspected.
- SHA pinning resolves the tag; it does not vet the action's code (that is `/dozer`'s class of
  review, treating actions as dependencies).
- Prompt-defined, with no end-to-end validation harness.

---

## Routing / escalation

| Situation | Route |
|---|---|
| Live credential in CI config or repo history | Draft to `#security-team`; assume compromised; security rotates |
| Complex trigger / credential-path change | `/architect` (read-only sub-call) |
| Branch also changes Terraform / K8s / IAM | `/hamann` |
| Org-level setting needs changing | Recommend to the owning team; never changed by Bane |
| Active exploitation suspected | `#security-team` → `/john-wick` |
