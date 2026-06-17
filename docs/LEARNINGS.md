# Learnings

Notes on patterns that emerged while building and operating the roster. These are
implementation-agnostic — they describe *why* the agents are shaped the way they are, so you
can adapt them to your own environment.

---

## The "keeper of the register" pattern

Security agents surface findings. But a finding isn't the end of the story — eventually a human
**decides** what to do with it: fix it, or accept the risk. Those accept decisions need to live
somewhere durable, or they evaporate.

Early on, every agent that produced a gating finding also tried to decide where it should be
recorded. That spread the same write logic — branch, validate, open a PR, enforce sign-off
rules — across a dozen skills, and they drifted apart.

The fix was to designate **one keeper of the risk register** (here, **The Keymaker**) and route
every "engineering accepted this risk" decision through it. One write path, one set of
guardrails, one schema authority.

**Why it's better:**

- **No duplicated write logic.** Producers detect the decision; the keeper records it.
- **One place to enforce policy.** Acceptance-authority rules (who can sign off on a high
  residual risk) live in the keeper, not scattered across skills.
- **The schema can't drift.** The keeper reads the register repo's own conventions doc as the
  single source of truth instead of carrying its own copy.

---

## Declined-blocker handoff

A **blocker** is a finding a review gates on — the change shouldn't ship until it's resolved.
But sometimes engineering decides to ship anyway and **accept** the risk. That decision is
exactly what belongs in the risk register.

So every skill that can produce a gating decision an engineer might override hands off to the
keeper when the engineer **explicitly accepts**:

- Pre-publication / repo reviews → remediate-vs-accept on each open blocker
- Code & design reviews → an "Accepted Risk" disposition on a follow-up question
- Vendor approvals → proceeding despite a "Not Approved" / "Limited" decision
- Vulnerability triage → a *real* finding that won't be fixed (a false positive is suppressed,
  not risk-accepted)
- Domain audits → an audit finding the team explicitly won't fix

**Guardrails that made this safe:**

- **Explicit-decision gate — no auto-creation.** An entry is created only on an explicit human
  accept. An unresolved-but-undecided finding records nothing.
- **Distinguish "suppress" from "accept."** A false positive is closed; only a real, accepted
  risk lands in the register. Conflating them pollutes the record.
- **Single-file PRs.** The keeper's change touches only the register file — a diff-scope check
  before opening the PR catches anything that slipped in.
- **Fresh read before write + concurrency check.** Re-fetch the register (and its file hash)
  immediately before writing, so two sessions don't clobber each other.
- **Graceful failure.** If the keeper can't reach the register repo, it surfaces exactly what's
  needed — the accepted risk is never silently dropped.

---

## Naming with intent

Agent names aren't just flavor — they encode the role, which helps humans route work. When an
agent's job changes, the name should follow.

The compliance agent began as a tidy records-keeper and grew into the hub the whole roster hands
accepted risks to. Its original name no longer described what it did, so it was renamed to **The
Keymaker** — the one who makes the keys (register entries) that let a finding pass into the
record. The rename was a deliberate signal that the role had become central, not incidental.

A small caution from doing it: pick names that don't collide with metaphors already in use
elsewhere in the roster, and remember that a rename ripples through routing tables, handoff
maps, and docs — but should **not** rewrite immutable identifiers (ticket URLs, existing branch
names) that legitimately still carry the old name.
