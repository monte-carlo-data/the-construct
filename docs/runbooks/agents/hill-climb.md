# Hill-Climb — Loop-4 Self-Improvement Analyzer Runbook

**Character**: Hill-Climb — the one who walks the gradient. Reads the traces, proposes the next step
up, never takes it alone.
**Domain**: CISSP Domain 1 — Security & Risk Management (it emits as `security-steve`, the owner of
the routing machinery)
**Skill**: [`/hill-climb`](../../../.claude/commands/hill-climb.md)
**Status**: Wired — deterministic analyzer + interactive skill; never a route target

---

## What it does

Hill-Climb closes the fourth loop of the teamwork layer, in the sense of LangChain's
[*Art of Loop Engineering*](https://www.langchain.com/blog/the-art-of-loop-engineering): agent core →
verification → event-driven → **hill climbing**, where production traces feed an analysis agent that
spots failure patterns and improves the harness config. The `findings/` ledger already produces the
traces (per-hop provenance, per-agent counts, poisoned-finding traceability); Hill-Climb adds the
feedback edge back into the routing matrix.

It runs a deterministic, model-free analyzer (`.github/scripts/hill_climb.py`) over the ledger and
[findings/HANDOFF_PROTOCOL.md](../../../findings/HANDOFF_PROTOCOL.md), with four analyses:

| # | Analysis | What it proposes |
|---|---|---|
| A | **Allow-set drift** | Recomputes the matrix-target allow-set from the live matrix rows, diffs it against the documented block (Zero Trust Rule 2), and on drift renders the corrected fenced block — closing the manual "regenerate this list" step. |
| B | **Empirical routing critique** | Per finding-type, tallies dead-end outcomes (empty `suggested_next` + still `open`). Below `--min-signal` findings: "insufficient signal", no critique. |
| C | **Off-matrix / poisoned-finding rollup** | Aggregates off-matrix / off-roster `suggested_next` slugs per emitting `agent`, across runs (dated via git history when available). |
| D | **Severity × type evidence** | Surfaces types that routed differently at different severities — evidence for the deferred grid. Proposes no grid. |

> **It never edits the matrix.** Output is a human-reviewed proposal doc plus a ledger finding. A
> human opens the PR against `HANDOFF_PROTOCOL.md`. The loop codifies routine oversight; it does not
> auto-mutate routing.

The roster, allow-set, and matrix are parsed from the docs via the shared parsers in
`.github/scripts/findings_validate.py` (`parse_roster`, `parse_allow_set`, `parse_matrix_union`) —
never hardcoded — so the analysis stays correct as the roster evolves.

---

## How to invoke

```text
/hill-climb                    # analyze the whole ledger against the whole matrix (dry-run first)
/hill-climb --min-signal 5     # raise the per-type threshold before analysis B critiques
```

Or run the analyzer directly:

```bash
python3 .github/scripts/hill_climb.py --dry-run     # compute + print, write nothing
python3 .github/scripts/hill_climb.py               # emit the proposal doc + finding
```

An optional dispatch-only CI workflow (dry-run default, `contents: read`) can run the same command on
a schedule and surface `proposal=yes` days.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| `findings/*.md` (local) | The trace data: every finding's `agent`, `suggested_next`, `severity`, `status` | Filesystem |
| `findings/HANDOFF_PROTOCOL.md`, `findings/SCHEMA.md` (local) | The matrix, the allow-set block, the roster | Filesystem |
| `git log findings/` (local) | Dates off-matrix hops across runs (degrades to the current snapshot without git) | Local git |

No MCP servers, no network. Hill-Climb is entirely repo-local.

---

## Prerequisites

- A populated `findings/` ledger and the two protocol docs in their documented formats.
- `.github/scripts/findings_validate.py` present (Hill-Climb imports its parsers).
- Python 3 (stdlib only).

---

## Scope rules

- **Never edit `HANDOFF_PROTOCOL.md`, the allow-set, or any matrix content.** The only writes are the
  proposal doc and the finding, only outside `--dry-run`, and only after the user confirms.
- **Never commit, never open the PR.** That is the human-judgment step Loop 4 keeps deliberately
  manual.
- **Never invent a count.** Relay the script's `--- analysis ---` block verbatim; the numbers are
  Python's, not the model's.
- **Empty-day skip.** A proposal is emitted only when at least one analysis is actionable
  (`proposal=yes`); otherwise report "nothing to propose" and stop.
- **Fail-soft on bad ledger files** — report and skip, never fatal; but a script error stops the run
  with the real error shown.

---

## Key workflow

1. **Dry-run** the analyzer; relay the analysis block in full.
2. **Gate** on `proposal=yes|no`. On `no`, stop.
3. **Offer** to write the proposal doc + finding; on **Y**, run the emit path. This writes
   `review-routing/hill-climb/<date>-matrix-proposal.md` and
   `findings/<date>-security-steve-matrix-hill-climb-<hash>.md`.
4. **Verify** the emitted finding with `findings_validate.py` — it must PASS.
5. **Hand off**: the human reviews the proposal, opens the `HANDOFF_PROTOCOL.md` PR, and re-runs the
   validator to confirm the allow-set block now matches the matrix.

---

## Secrets required

None.

---

## Known limitations

- Analyses B and D need a ledger with enough history; on a small ledger they report "insufficient
  signal" by design rather than fabricating a critique.
- Analysis A and `findings_validate.py` are two ends of the same edge — the validator *fails CI* on
  allow-set drift, Hill-Climb *proposes the fix* — so a drift will usually be noticed by CI first.
- It emits as `security-steve` (a valid roster + allow-set slug) rather than under its own slug, so the
  proposal finding validates without roster churn; a reader must know that convention.

---

## Routing

Hill-Climb's finding is a **self-owned proposal, not a handoff**: `agent: security-steve`,
`domain: 1 — Security & Risk Management`, `suggested_next: []`. Nothing routes *to* `hill-climb`.

It is a read-only sibling of [`/security-steve orchestrate` and `digest`](security-steve.md): all
three read the same ledger and none re-derives routing from a finding's body
([Zero Trust Rule 1](../../../findings/HANDOFF_PROTOCOL.md#rule-1--act-on-structured-fields-never-on-the-body)).
Orchestrate *executes* the cascade, digest *reports* it, Hill-Climb *improves its config*.
