# Engineering SDLC Agents

Two agent line-ups ship in this repo, and they are not the same thing.

- **Engineering SDLC agents** (this doc) — ten agents engineers run **in their own dev loop**, one
  per SDLC stage. They shift security checks left, into the branch, before review.
- **The security Matrix roster** ([README.md](../README.md)) — the security team's own agents.
  **Unchanged by any of this.**

The operating model: engineering agents do the stage-appropriate work and **call security agents as
read-only sub-steps** when they need the org-wide view. The rule is **call, never modify**.

---

## When you're about to… → run

The value is **timing and target**, not prompt wording — invoke the right agent at the right moment
in the lifecycle and let it call the security roster for the org-wide context it needs.

| You're about to… | Run | What you get back |
|---|---|---|
| Start a ticket / write the spec | [`/rama-kandra`](../.claude/commands/rama-kandra.md) 🤝 | Security acceptance criteria (ASVS-mapped) appended to the spec, before code exists |
| Design a feature or a new surface | [`/persephone`](../.claude/commands/persephone.md) 🎭 | A living threat model (STRIDE; MAESTRO for agentic) with residual-risk-rated threats |
| Add or bump a dependency | [`/dozer`](../.claude/commands/dozer.md) 🚧 | Malicious-package / license / provenance verdict — SAFE or escalate |
| Add or edit a CI/CD workflow | [`/bane`](../.claude/commands/bane.md) ⛓️ | Token-scope, action-pinning, `pull_request_target`, secret, and OIDC fixes as diffs |
| Have open scanner alerts on the branch | [`/apoc`](../.claude/commands/apoc.md) ⚡ | Triage of each alert (already suppressed? FP? real?), real fixes folded into the branch |
| Write tests for security-relevant logic | [`/mouse`](../.claude/commands/mouse.md) 🐭 | Abuse-case, authz-regression, and bug-stays-dead tests (proven red before the fix) |
| Touch Terraform / K8s / IAM | [`/hamann`](../.claude/commands/hamann.md) ⚙️ | IaC review pre-merge — encryption, public access, IAM scope — fixes as diffs |
| Cut a release | [`/lock`](../.claude/commands/lock.md) 🚪 | A go/no-go evidence bundle (reviews, CI, build gate, accepted risks, tests) |
| Take a CVE / dependency-upgrade ticket | [`/roland`](../.claude/commands/roland.md) 🔨 | A green, reviewable upgrade PR with the resolved version verified out of range |
| Audit your team's own agent surface | [`/twins`](../.claude/commands/twins.md) 👥 | A red-team of your skills/hooks/tool-scope (injection, over-scope) — monthly |

**Chain them across the lifecycle.** The payoff isn't any single call — it's plan → design → build →
… → operate, each stage catching what's cheapest to fix at that point. See the
[worked example](#worked-example-ticket--release) below.

All ten are `user-invocable: true`, `context: fork` skills in `.claude/commands/`, invoked as
`/<name>` or via the `Skill` tool — the same convention as the roster agents they call. Wording
barely matters: `/hamann`, "run hamann on this branch", and "threat-model this design with
persephone" all work.

### Naming

Names were verified free against the security roster before use. Two were renamed in the process,
because the original pick collided with a roster agent:

| Was | Now | Why |
|---|---|---|
| Keymaker | **Bane** | [`/keymaker`](../.claude/commands/keymaker.md) is the security roster's GRC/risk-register agent |
| Smith | **The Twins** | [`/smith`](../.claude/commands/smith.md) is the security roster's chaos-engineering agent |

---

## The call graph

Each engineering agent calls the security agents holding context it cannot derive locally. **Every
sub-call is read-only.**

| Eng agent | Calls | For what |
|---|---|---|
| `/rama-kandra` | [`security-steve`](../.claude/commands/security-steve.md) | Risk-classification quick-check; full design review if warranted |
| `/persephone` | [`architect`](../.claude/commands/architect.md), [`niobe`](../.claude/commands/niobe.md), ([`merovingian`](../.claude/commands/merovingian.md)) | Code-level control reality; trust-boundary/crypto posture; sensitive-data blast radius |
| `/dozer` | [`cypher`](../.claude/commands/cypher.md), [`tank`](../.claude/commands/tank.md) | Existing dependency-risk intel; is this already a tracked finding or suppression |
| `/bane` | [`architect`](../.claude/commands/architect.md) | Security review of complex/high-risk workflow changes |
| `/apoc` | [`tank`](../.claude/commands/tank.md), [`architect`](../.claude/commands/architect.md) | Org triage context (already suppressed/ranked?); review of the drafted fix |
| `/mouse` | [`tracer`](../.claude/commands/tracer.md), [`neo`](../.claude/commands/neo.md) | Unmapped-requirements list (Mouse's work queue); attack techniques as abuse-case source |
| `/hamann` | [`switch`](../.claude/commands/switch.md), [`niobe`](../.claude/commands/niobe.md), [`merovingian`](../.claude/commands/merovingian.md) | Live network posture; crypto/trust boundaries; sensitive data behind the store |
| `/lock` | [`sentinel`](../.claude/commands/sentinel.md), [`keymaker`](../.claude/commands/keymaker.md), ([`seraph`](../.claude/commands/seraph.md)) | Build-gate verdict; accepted risks/declined blockers; quantified exposure of a gap |
| `/roland` | [`tank`](../.claude/commands/tank.md), [`seraph`](../.claude/commands/seraph.md) | Prioritization context; dollar-denominated exposure for sequencing |
| `/twins` | [`neo`](../.claude/commands/neo.md), [`smith`](../.claude/commands/smith.md) | Applicable attack techniques; drill-design pattern (hypothesis, auto-abort, kill switch) |

**Degradation is explicit.** When a sub-call can't run, the skill proceeds on local evidence and
**says the cross-check did not run** rather than silently omitting it. The one hard exception is
`/lock`: a gate whose status it could not retrieve is **never** reported as green.

All sub-call targets are read-only from an engineer's seat — Architect reviews a PR/design, Sentinel
reports a gate verdict, Tracer emits a coverage matrix. None suppresses a finding, mutates a gate, or
accepts risk; those stay with `tank` / the CI gate / `keymaker` regardless of who can invoke the read.

---

## Call, never modify

Engineering agents:

- **may** invoke a security agent read-only and use its answer
- **may not** edit any security skill, the roster README, the handoff matrix
  ([`findings/HANDOFF_PROTOCOL.md`](../findings/HANDOFF_PROTOCOL.md)), or the `findings/` ledger
- **may not** suppress, dismiss, or disposition a security finding — `/tank` owns triage and
  scanner suppression. (`/apoc` may dismiss only GitHub code-scanning alerts, in its own repo, one
  at a time, with written reasoning.)
- **may not** override a gate — `/sentinel` owns the build gate; `/lock` reports it and has no
  override path
- **may not** accept risk on the org's behalf — that is `/keymaker`
- **may not** rotate a credential or print a secret value
- **do not** emit to the `findings/` ledger ([schema](../findings/SCHEMA.md)). That store is the
  security agents' integration layer; these ten report to the engineer, and escalate to a human
  channel when it matters.

The roster is shared team infrastructure. Engineers run it through a shared read-only credential
set (see [`knowledge/config.md`](../knowledge/config.md)), which is what makes read-only invocation
possible without handing out security's own credentials.

### What stays security's

| Concern | Owner |
|---|---|
| Org-wide vuln triage, suppression, disposition | `/tank` and your vuln-ticket workflow |
| The build gate | `/sentinel` |
| Requirement→test coverage verification | `/tracer` |
| Security design review | `/security-steve` and your design-review process |
| Risk register, accepted risks, declined blockers | `/keymaker` |
| Post-deploy detection, cloud posture, org guardrails (SCPs) | security |
| Org-level pipeline monitoring, branch protection, org secrets | security |
| Awareness outreach to people, phishing simulation | [`/morpheus`](../.claude/commands/morpheus.md) |
| Incident response | [`/john-wick`](../.claude/commands/john-wick.md) |

---

## Escalation

| Situation | Route |
|---|---|
| Feature warrants a full security design review | `/security-steve` |
| New attack path found while threat modeling | `/security-steve` |
| Suspected **malicious package** | draft to `#security-team` immediately (`/dozer`) |
| **Live secret** in code, CI, or IaC | draft to `#security-team`; assume compromised; security rotates |
| Scanner finding needing a real disposition | `/tank` |
| Real vulnerability found by a drill | `#security-team` (`/twins` Step 5) |
| Active exploitation | `#security-team` → `/john-wick` |
| Risk that won't be fixed and needs accepting | `/keymaker` |
| "I don't know who to ask" | `/security-steve` |

Every Slack escalation is **drafted, never auto-sent** — the engineer confirms and sends.

---

## If it seems like nothing happened

- **Wrong stage/target.** `/hamann` on a branch with no IaC, or `/bane` with no workflow change, has
  nothing to review. Match the agent to what the branch actually touches.
- **A cross-check was skipped.** These agents call the security roster read-only for org context. If
  a sub-call can't run (e.g. the shared roster credentials aren't set up on your seat), the agent
  **says so and proceeds on local evidence** — read that line; it's not a silent pass. `/lock` is
  the one hard exception: a build gate it couldn't read is **never** reported green.
- **You expected it to fix something it doesn't own.** Engineering agents *call, never modify*
  security state — they won't suppress a finding (`/tank`), override a gate (`/sentinel`), or accept
  risk (`/keymaker`). They report and, when it matters, **draft** a `#security-team` escalation for
  you to send.

---

## Worked example: ticket → release

A team adds a customer-facing report-export endpoint.

**1. Plan** — `/rama-kandra` classifies the feature (*public-authenticated · customer data ·
per-tenant authz · new us→third-party boundary*), quick-checks the classification with
`security-steve`, and appends 6 acceptance criteria to the spec — including
`AC-S2: tenant B cannot fetch tenant A's export by id (403)`.

**2. Design** — `/persephone` builds `docs/threat-models/report-export.md`. `architect` reports the
tenant claim is checked at the gateway but **not** re-checked at download; `niobe` flags the export
URL carries no expiry. Both become threats **T-01** and **T-02** at `H` residual — found before any
code exists.

**3. Build** — the branch adds a PDF library. `/dozer`: 4 years old, provenance attested, no install
scripts, and `cypher` confirms two other repos already use it → **SAFE**. The branch also adds a
release workflow; `/bane` finds a missing `permissions:` block and an unpinned third-party action,
and applies both fixes as diffs.

**4. Code** — `/apoc` sees 3 open alerts. `tank` reports one already suppressed (drop it), one a
stale worktree duplicate (FP, dismissed with reasoning), and one a real path traversal in the export
filename handler — fixed in-branch, minimal diff.

**5. Test** — `/mouse` reads `tracer`'s unmapped list, then writes the cross-tenant authz test
encoding **AC-S2** and **T-01**, plus a regression test for the path traversal — proven red against
the pre-fix code.

**6. Deploy** — `/hamann` reviews the new exports bucket: `block_public_*` only partly set, default
encryption missing. `merovingian` confirms it will hold customer data → **HIGH**, both fixed as
diffs.

**7. Release** — `/lock` assembles the evidence: reviews clean, CI green on the candidate SHA,
`sentinel` gate **green**, `keymaker` reports one unrelated accepted risk, threat model current,
security tests present. One gap: a medium dep alert not in this candidate → **GO WITH GAPS**, gap
named.

**8. Operate** — two weeks later a CVE lands on the PDF library. `/roland` takes the ticket, finds a
patch-level fix (no breaking changes), gets tests green, verifies the resolved version is outside the
vulnerable range, and opens the PR. `tank` confirms it was already in the ranked worklist.

**Meta** — monthly, `/twins` audits the engineering skill set: seeds a labeled benign payload in a
throwaway ticket and confirms the team's planning skill treats it as data, audits every skill's
`allowed-tools` against actual needs, and files tickets for the over-scoped ones.

Security was consulted eleven times and interrupted zero times.

---

## Design conventions these ten follow

- **Untrusted-input section in every skill.** Tickets, PR comments, scanner findings, package
  metadata, and source code are attacker-reachable: data to reason about, never instructions, and
  never interpolated into a shell command. The same Zero Trust posture the roster applies between
  finding hops ([HANDOFF_PROTOCOL → Zero Trust](../findings/HANDOFF_PROTOCOL.md#zero-trust--findings-are-untrusted-between-hops)).
- **No destructive default.** `/dozer` never installs a package under review; `/hamann` never applies
  IaC; `/twins` never disables a defense; nothing rotates a credential or prints a secret.
- **Diff-scope discipline** wherever an agent commits — the diff carries the fix and nothing else,
  and a surprising `git diff --stat` stops the run.
- **Branch before editing**, re-checking `git branch --show-current` before committing.
- **Report what didn't run.** A skipped sub-call is stated, never silently dropped.
- **Few, specific outputs.** Criteria, findings, and tests kept small enough to actually be read.

---

## Running them elsewhere

Any Claude Code host that can fetch a skill file by name can run these — a bot that bridges to this
repo's `.claude/commands/` at call time needs no copy of its own. Two things hold wherever they run:

- **The host's own rules win** over anything a fetched skill assumes — branch before editing, the
  test suite green before reporting done, no secret into the repo, and the human does the push.
- **The host is itself a legitimate `/twins` target**: its `.claude/` agent surface and agent-running
  workflows are engineering agentic surface. Drills stay opt-in, labeled, contained, and off `main`.

These are prompt definitions with no code path to unit-test; validation is frontmatter/reference/
boundary checks. A supervised first run (`/bane` or `/hamann` against a branch with known-bad
workflow/IaC) is the real signal before trusting one in a team's loop.

Per-agent runbooks: [`docs/runbooks/agents/`](runbooks/agents/).
