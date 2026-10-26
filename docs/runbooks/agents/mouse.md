# Mouse — Security Test Authoring Agent Runbook

**Character**: Mouse — built the training simulations; the safe place to meet something dangerous
**Line-up**: Engineering SDLC agents — **Test** stage ([line-up guide](../../engineering-sdlc-agents.md))
**Skill**: [`/mouse`](../../../.claude/commands/mouse.md)
**Status**: Wired — interactive skill; calls the security roster read-only; never emits to `findings/`

---

## What it does

Mouse writes the security tests that ship **with** the feature: regression tests that keep a fixed
bug dead, authorization tests (including the cross-tenant case), input-validation / abuse-case tests
derived from the real sinks in the change, and security-control tests (rate limits, audit events,
fail-closed). It learns the repo's test idiom first and extends existing test files — security tests
are just tests.

Its work queue comes from [`/tracer`](../../../.claude/commands/tracer.md): the unmapped
security-requirements list for the repo *is* what Mouse should write next. A new test that fails
against current code is reported as a **missing control**, never weakened to pass.

## How to invoke

```text
/mouse                          # infer from the branch: authz, input handling, or a security fix?
/mouse SEC-1234                 # encode the vulnerability a ticket describes as a regression test
/mouse src/api/exports.py       # abuse cases + authz surface of a file or function
/mouse abuse-cases              # the feature on this branch, abuse-case first
```

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Local repo + git | Detect test idiom, read changed files, write and run tests | none (local) |
| Linear (`get_issue`) | Resolve a ticket/finding to the vulnerability to encode | Linear MCP (OAuth) |
| `/tracer` (roster, read-only) | Unmapped security requirements for this repo | roster credentials, read-only |
| `/neo` (roster, read-only) | Realistic attack shapes for abuse-case tests | roster credentials, read-only |

## Prerequisites

- A checked-out branch with the change under test; a test runner the repo already uses.
- Linear MCP configured only if you pass a ticket id.
- Roster credentials for the read-only sub-calls (see [`knowledge/config.md`](../../../knowledge/config.md)).
  Without them Mouse proceeds from the code and states that the coverage gap was not verified.

## Scope rules

- **Tests run locally and in CI against fixtures only.** Mouse never attacks a deployed system.
- **Never invents a framework.** It states the detected idiom before writing; a repo with no
  framework gets plain tests in that repo's convention.
- **Never deletes or weakens an existing test** to make a suite pass — a failing security test is a
  finding for the engineer.
- No real credentials, customer data, or PII in fixtures.
- Writes 3–8 specific tests, not 30 that assert nothing. If the branch touches nothing
  security-relevant and no target was given, it says so and stops.

## Key workflow

1. **Learn the idiom** — framework, runner, file naming, fixtures, the suite command; read 2–3
   neighbouring tests.
2. **Build the queue** — from the ticket, file, `abuse-cases`, or inferred from the diff; prefer
   `/tracer`'s unmapped requirements over guesses; ask `/neo` for attack shapes.
3. **Choose** — regression ("bug stays dead", proven red against pre-fix code) → authz
   (401/403/cross-tenant/404-same-shape) → input validation from actual sinks → control tests.
4. **Write and run** — in the repo's idiom, extending the existing file, one comment naming the
   threat per test; report actual suite output.
5. **Report** — idiom, tests added by kind, suite result, tests failing against current code
   (= missing controls), sub-calls that ran or didn't.

## Roster sub-calls (read-only)

| Agent | Question |
|---|---|
| `/tracer` | Which security requirements in this repo have no mapped test? (the work queue) |
| `/neo` | Known attack techniques applicable to this endpoint / auth model / data flow? |

## Secrets required

None of its own. Roster sub-calls use the shared read-only roster credentials; Linear uses the MCP OAuth session.

## Known limitations

- Proving a regression test red requires the pre-fix code to be reachable (a prior commit or a local
  revert); when it isn't, the report says "proven red: no".
- Cross-tenant tests need two real fixture tenants — if the repo has no tenant fixture, Mouse
  surfaces that as its own gap rather than faking it.

## Routing / escalation

| Situation | Route |
|---|---|
| A new test fails against current code (control missing) | tell the engineer → [`/apoc`](../../../.claude/commands/apoc.md) to fix in-branch |
| Looks exploitable in production today | draft to `#security-team` (engineer sends) |
| Coverage gap needs a requirement written, not a test | your spec/requirements workflow (`/rama-kandra`) |

Mouse does not emit to the `findings/` ledger; it reports to the engineer.
