# Logos — Program-Metrics Scorecard Agent Runbook

**Character**: Logos from *The Matrix* — the hovercraft / "the word"; turns scattered signals into one statement
**Domain**: CISSP Domain 1 — Security & Risk Management (OWASP SAMM Governance / Strategy & Metrics)
**Skill**: [`/logos`](../../../.claude/commands/logos.md)
**Status**: Wired — emit-only in the findings roster; a scheduled CI job is a designed-for follow-up

---

## What it does

Logos owns the **security program scorecard** — the unclosed core of SAMM Strategy & Metrics. It is
an **aggregator, not a scanner**: it pulls three signals the fleet already produces into one
board-ready page, scores each against a configured target, and **acts** on breaches.

The three inputs:

- **FAIR exposure** — Seraph's `.seraph/reports/*/results.json` (highest standing P95, calibration).
- **Open-vuln aging** — your vuln-tracking Linear team (the vuln-ticket workflow's output): overdue
  count + oldest age.
- **SAMM coverage** — your security dashboard's `const SAMM` array (the SAMM-audit artifact):
  full/gap tallies.

On a breach, Logos opens a deduped Linear issue (your agent-tracking project) and emits a `findings/`
hand-off routed onward — to Seraph (quantify), Keymaker (register), or Security Steve (program gap).
This act-on-breach loop is what earns Strategy & Metrics a `full` SAMM score: a real agent runs on a
trigger, routes to an owner, and leaves evidence.

> Logos invents no telemetry and re-scores no SAMM practices. Its value is the single page and the
> act-on-breach loop — not new scanning. A missing source reads `n/a`, never a false on-track.

---

## How to invoke

```text
/logos                  # full scorecard: pull all sources, score, write the page, act on breaches
/logos <metric-id>      # refresh just one metric row (optional)
```

Targets live in `programs/scorecard/logos-metrics.yaml` — re-targeting the program is a one-line PR
against that file, never a skill-body edit.

---

## Outputs

- **Scorecard** — `programs/scorecard/Security_Program_Scorecard.md` (generated artifact; sync it to
  your knowledge base if your team keeps board docs there).
- **Linear** — one deduped issue per breach in your agent-tracking project (Security team, Triage).
- **Findings** — one schema-valid `findings/*.md` per breach (`agent: logos`, Domain 1).

---

## Routing (findings hand-offs)

Logos is **emit-only**: it appears in the `agent` field and routes findings *out*; nothing routes
*to* `logos` (a scorecard is a source, not a sink — a hop to it is an off-matrix poisoning signal).
Slices of [findings/HANDOFF_PROTOCOL.md](../../../findings/HANDOFF_PROTOCOL.md):

| Breach type | `suggested_next` | Matrix row |
|---|---|---|
| FAIR exposure over target | `[seraph]` | 14 |
| Breach needing a register treatment decision | `[keymaker]` | 18 |
| SAMM coverage / program gap (cross-domain) | `[security-steve]` | 19 |
| Vuln-aging breach with compliance implication | `[keymaker]` (+ `seraph` if a $-figure sharpens it) | 13 |

---

## Relationship to the rest of the roster

- **The SAMM audit** scores the 15 practices and keeps the dashboard array honest; Logos *consumes*
  that array as one of three inputs. The SAMM audit is the coverage auditor; Logos is the metrics
  owner. Logos references — never duplicates — the SAMM audit's per-practice gap tickets.
- **Seraph** quantifies a single risk in dollars; Logos surfaces the *standing* exposure across all
  Seraph reports and routes a breach back to Seraph for a fresh business case.
- **The vuln-ticket workflow** creates and ages the vuln issues; Logos reads their aging as a metric.

---

## Caveat — capability, not usage

Logos measures the program's **wired-up signals**, not how often any agent ran. A `full` SAMM count
means the loop *can* close, not that it fired this week. Real per-agent usage lives in the findings
ledger. State this when presenting the scorecard.
