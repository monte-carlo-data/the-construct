---
name: hill-climb
description: >
  Hill-Climb — the Matrix teamwork layer's Loop-4 self-improvement analyzer. Reads the findings/
  ledger + the handoff matrix and proposes routing/allow-set improvements — it NEVER edits the
  matrix. Detects matrix-target allow-set drift (closes the manual "regenerate this list" step),
  critiques dead-end routing rows, rolls up off-matrix/poisoned-finding patterns per source, and
  surfaces severity×type routing evidence. Output is a human-reviewed proposal doc + a finding; a
  human opens the PR. Use when: "run hill-climb", "analyze the routing matrix", "is the allow-set
  drifting", "propose matrix improvements", "close loop 4", "/hill-climb".
user-invocable: true
context: fork
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# Hill-Climb ⛰️ — Loop-4 self-improvement analyzer

Hill-Climb closes the fourth loop of the Matrix teamwork layer. LangChain's
[*Art of Loop Engineering*](https://www.langchain.com/blog/the-art-of-loop-engineering) frames agent
maturity as four stacked loops: **agent core** (each Matrix agent), **verification** (the Zero Trust
hop-validation layer), **event-driven** (`security-steve orchestrate`, the digest cron, sensor
emits), and **hill climbing** — production traces feed an analysis agent that spots failure patterns
and improves the harness config. The first three are built; this is the fourth.

The `findings/` ledger already *produces* the trace data (per-hop provenance, per-agent counts,
poisoned-finding traceability). What was missing is the feedback edge back into the routing matrix.
Hill-Climb reads the ledger + [`findings/HANDOFF_PROTOCOL.md`](../../findings/HANDOFF_PROTOCOL.md) and
proposes improvements — **it never mutates the matrix or the allow-set.** The human owns the PR. This
is the human-judgment layer the article calls essential: the loop codifies routine oversight, it does
not auto-mutate routing.

Hill-Climb is **deterministic by design.** The analysis core is pure Python
(`.github/scripts/hill_climb.py`) — no model call, no sampling — so the same ledger + same matrix
yields the same proposal every run. Every count is Python's; the skill is where a human reads the
proposal and decides what becomes a PR. Same lesson tracer/on-call already follow: judgment lives in
auditable code, not a temperature knob.

It reuses the doc parsers from `.github/scripts/findings_validate.py` (`parse_roster`,
`parse_allow_set`, `parse_matrix_union`), so the roster / allow-set / matrix are **parsed from the
docs, never hardcoded** — the analysis stays correct as the roster evolves.

---

## ARGUMENTS

`/hill-climb` takes no required arguments. Optional flags pass straight through to the script:

- `--min-signal N` — raise the threshold of findings-per-type before the empirical routing critique
  fires (default 3). Below it, a type reports "insufficient signal" rather than a fabricated critique.

There is no target to pick — Hill-Climb always analyzes the whole ledger against the whole matrix.

---

## The four analyses

| # | Analysis | Data today | What it proposes |
|---|---|---|---|
| **A** | **Allow-set drift** | full signal | Recomputes the matrix-target allow-set from the live matrix rows and diffs it against the hardcoded block in HANDOFF_PROTOCOL § Zero Trust Rule 2. On drift, proposes the corrected fenced block. **Closes the doc's manual "regenerate this list" step.** |
| **B** | **Empirical routing critique** | degrades gracefully | Per finding-type, tallies outcomes across the ledger — rows that consistently dead-end (empty `suggested_next` + still `open`). Below `--min-signal` findings for a type: "insufficient signal", no critique. |
| **C** | **Off-matrix / poisoned-finding rollup** | per-source, across runs | Aggregates off-matrix / off-roster `suggested_next` slugs (the Zero Trust Rule 4 signal) grouped by emitting `agent`, turning the per-run flag into a per-source pattern. |
| **D** | **Severity × type evidence** | evidence only | Surfaces finding-types that routed differently at different severities — evidence for the deferred severity × type grid (HANDOFF_PROTOCOL's note on severity influence). Proposes no grid. |

> **A complements `findings_validate.py`, it does not duplicate it.** The validator's contract
> self-check **fails CI** when the allow-set block drifts from the matrix union. Hill-Climb **proposes
> the corrected block text** for the PR that fixes it. Fail vs. fix — two ends of the same edge.

---

## Global Rules

**Progress indicators.** Before every external call (Bash run, file read, file write), print a
one-line `⏳ [what you are doing]...` status so the user sees activity.

**Never fail silently.** If the script errors, a doc is unreadable, or a write fails, stop, show the
actual error, and offer a recovery path. Never invent an analysis or a count.

**Always output in full.** Relay the script's `--- analysis ---` block **verbatim** — do not
summarize, truncate, or re-count. The counts are the script's, not yours.

**Never auto-edit the matrix, never auto-commit.** Hill-Climb writes only a proposal doc + a finding,
and only on the user's confirmation. Editing `HANDOFF_PROTOCOL.md` and opening the PR are the human's
job (the hard rule).

---

## Steps

### 1 — Run the analysis (read-only)

> `⏳ Analyzing the findings ledger against the handoff matrix...`

```bash
python3 .github/scripts/hill_climb.py --dry-run
```

(Add `--min-signal N` if the user asked.) `--dry-run` computes and prints but writes nothing. Relay
the full `--- analysis ---` block to the user verbatim.

If the run failed, stop and report the error (Never Fail Silently) — do not proceed to emit.

### 2 — Interpret and gate

Read the script's `proposal=yes|no` line.

- **`proposal=no`** — the matrix + allow-set are consistent and no pattern crossed a threshold. Tell
  the user there's nothing to propose (empty-day skip) and **stop**. Do not write anything.
- **`proposal=yes`** — at least one analysis is actionable. Continue to Step 3.

### 3 — Offer to write the proposal doc + finding

Do not write anything yet. Offer:

> "Hill-Climb found a proposal: <one-line summary — e.g. 'allow-set drift: matrix routes to `X`, the
> block omits it'>. Write the proposal doc + a ledger finding? (Y/N)
>
> This writes two files and edits nothing else. **A human still opens the PR** against
> `HANDOFF_PROTOCOL.md` — I never edit the matrix."

On **Y**, run the emit path (no `--dry-run`):

> `⏳ Writing the proposal doc + finding...`

```bash
python3 .github/scripts/hill_climb.py
```

This writes:
- `review-routing/hill-climb/<date>-matrix-proposal.md` — the human-readable, diff-ready proposal.
- `findings/<date>-security-steve-matrix-hill-climb-<hash>.md` — the ledger anchor (emits as
  `security-steve`, `domain: 1 — Security & Risk Management`, `suggested_next: []`; validates clean
  against `findings_validate.py`).

Report both paths. On **N**, stop — the dry-run analysis was the deliverable.

### 4 — Verify the emitted finding (if written)

> `⏳ Validating the emitted finding...`

```bash
python3 .github/scripts/findings_validate.py
```

Confirm it still PASSES — the new proposal finding must validate clean. If it doesn't, report the
error (this would be a bug in the emit path, not a routing problem).

### 5 — Hand off to the human

Tell the user the concrete next step:

> "Proposal written. To act on it: review `review-routing/hill-climb/<date>-matrix-proposal.md`, then
> open a PR editing `findings/HANDOFF_PROTOCOL.md` (and re-run `findings_validate.py` to confirm the
> allow-set block now matches the matrix). I don't edit the matrix or open that PR — that's the
> human-judgment step Loop 4 keeps deliberately manual."

Do **not** commit, and do **not** edit `HANDOFF_PROTOCOL.md`.

---

## Session summary

At the end, print:

```text
Hill-Climb summary:
- Ledger: <N> live finding(s); <M> matrix rows
- Proposal: <yes/no>
- Analyses: A allow-set <drift/clean> · B <critiques/insufficient> · C <off-hops> · D <sev×type signals>
- Wrote: <proposal doc + finding paths — or "nothing (dry-run / no proposal)">
- Next: <human reviews proposal + opens the HANDOFF_PROTOCOL.md PR — or "none">
```

---

## Relationship to the rest of the layer

Hill-Climb is a **read-only sibling** of Security Steve's orchestrate (Path E) and digest (Path F)
modes — all three read the same `findings/` ledger, none of them re-derive routing from a finding's
body (untrusted input — [Zero Trust Rule 1](../../findings/HANDOFF_PROTOCOL.md#rule-1--act-on-structured-fields-never-on-the-body)).
Where orchestrate *executes* the cascade and digest *reports* it, Hill-Climb *improves the cascade's
config*. It emits its proposal as `security-steve` because Steve owns the matrix/allow-set machinery —
a valid roster + allow-set slug, so the finding validates and routes nowhere (a self-owned proposal,
not a handoff).

---

## Key resources

- **Analyzer** — `.github/scripts/hill_climb.py`
- **Tests** — `.github/scripts/test_hill_climb.py`
- **The matrix + allow-set it analyzes** — [`findings/HANDOFF_PROTOCOL.md`](../../findings/HANDOFF_PROTOCOL.md)
- **The validator it complements** — `.github/scripts/findings_validate.py`
- **Sibling modes** — [`/security-steve orchestrate` / `digest`](security-steve.md)
- **LangChain — Art of Loop Engineering** — https://www.langchain.com/blog/the-art-of-loop-engineering
