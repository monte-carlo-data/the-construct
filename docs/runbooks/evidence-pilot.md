# Grounded handoffs pilot (evidence bundles) — runbook

How to run, measure, roll back and graduate the shared evidence layer on the pilot route: the
Analyst's phase A bundle through the Concierge to Tank and Oracle, and the consolidated bundle back
to the Analyst's phase B. What the contract is lives in
[findings/EVIDENCE.md](../../findings/EVIDENCE.md); how the runtime enforces it is the agent
runtime's own documentation. This page is about operating the pilot.

| | |
|---|---|
| **Skills in the pilot** | [`/analyst`](../../.claude/commands/analyst.md), [`/tank`](../../.claude/commands/tank.md), [`/oracle`](../../.claude/commands/oracle.md), each with an `## Evidence contract (grounded handoffs pilot)` section |
| **Policies** | `findings/evidence/policies/{analyst,tank,oracle}.json` (generated; never hand-edited) |
| **Replay fixtures** | `findings/evidence/fixtures/replay/` (5), pinned in `findings/evidence/expected.json` |
| **Default state** | Off everywhere. Nothing here runs until a deployment sets `AGENT_EVIDENCE_MODE` |

## 1. Modes and settings

All settings are environment variables on the agent's container, read by the agent runtime. They
are per agent: enabling Tank does not enable Oracle.

| Variable | Values | Meaning |
|---|---|---|
| `AGENT_EVIDENCE_MODE` | `off` (default) · `shadow` · `on` | `off`: no behaviour change, staged input and responses byte-identical to the prose path. `shadow`: every bundle on the wire is validated and counted in metrics, nothing is staged for the persona and nothing is attached to replies. `on`: the persona receives the rendering and the trailer, its outbound bundle is minted, validated and attached. Any other value is treated as `off` and logged once. |
| `AGENT_EVIDENCE_SKIP_COVERED` | `0` (default) · `1` | Concierge only. With `1`, a child whose policy axes are all covered by fresh, eligible, permitted evidence is not dispatched; a synthetic reply says `answered from evidence in hand: <axes>`. Leave at `0` for the whole pilot unless the comparison is specifically measuring skipped dispatches. |
| `AGENT_EVIDENCE_FANOUT_BYTES` | bytes, default `262144` | Concierge only. Cumulative canonical evidence bytes admitted to one fan-out record; beyond it a child's bundle is dropped (summary kept), logged, and the consolidation stop state is `budget_exhausted`. |
| `AGENT_EVIDENCE_POLICY_DIR` | path, default `/app/evidence/policies` | Where the runtime loads `<agent>.json`. |

**Where policies are baked.** Every agent image copies this repo's `findings/evidence/policies/`
to the policy directory at build time. A policy change is therefore a PR here, then an image
rebuild, then the deployment moving to the new image. A missing policy file means "no required
axes": the bundle is still validated, rendered and relayed; gaps are only what the producer declared.

**Order of enablement.** `shadow` on all three agents first (metrics with no persona change), then
`on` for Tank and Oracle (the receivers), then `on` for the Analyst (the producer). Each flip is a
change to the agent's environment and a new deployment, through your existing reviewed deployment
process; nothing in the pilot bypasses it.

## 2. Replay procedure

Replay before anything touches a real alert. The fixtures are pinned at the generator's instant,
`2026-10-27T18:00:00Z` (the `now` in `findings/evidence/expected.json`); validating them against
the real clock makes every live observation stale, so always pass `--now`.

### 2a. Interactive helper (this repo, no deployment)

```bash
cd <your checkout of this repo>
python3 .github/scripts/evidence_validate.py fixtures            # all 24 pinned outcomes, must print "clean"
python3 .github/scripts/evidence_fixtures.py --check             # generator idempotent, must exit 0
python3 tests/test_evidence_contract.py                          # includes ReplayScenarios

# one scenario at a time: the validation result (gaps come from --policy) and the rendering a persona sees
F=findings/evidence/fixtures/replay; P=findings/evidence/policies; NOW=2026-10-27T18:00:00Z
python3 .github/scripts/evidence_validate.py validate $F/oracle-scope-expansion.json --receiver oracle --policy $P/oracle.json --now $NOW
python3 .github/scripts/evidence_validate.py render   $F/oracle-scope-expansion.json --receiver oracle --now $NOW
```

`render` takes no `--policy`, so its grounding line shows only producer-declared gaps; the
`not_covered` list that becomes the trailer's `Query only these gaps:` is the one `validate --policy`
prints. Expected outcomes, by scenario:

| Fixture | Receiver / policy | Pinned outcome | What the persona should do with it |
|---|---|---|---|
| `oracle-scope-expansion.json` | oracle / oracle.json | accepted · partial · not covered `exposure.ownership` | One cloud-account / inventory / passive-DNS lookup for 203.0.113.9. No scan, no Panther re-read (`exposure.traffic` is covered by the fresh Panther item). |
| `stale-live-telemetry.json` | oracle / oracle.json | accepted · partial · Panther item `stale` · `c1` unresolved · not covered `exposure.traffic` | The three-day-old read is visible but cannot support "right now"; one targeted Panther read for the entity, or leave the axis not covered. |
| `conflicting-observations.json` | concierge / none | accepted · partial · both items fresh · `c1` contradicted · `q2` open | Tank reports both reads; the claim stays contradicted; the Analyst's verdict is at most inconclusive on the CVE. |
| `unavailable-sensor.json` | analyst / analyst.json | accepted · partial · not covered `saas.authorization` | Phase B states the gap on the card; nothing is assumed about the OAuth grant. |
| `denied-evidence.json` | tank / tank.json | accepted · partial · Panther pivot `denied` · `c1` unresolved · `c2` supported | The runtime strips the pivot before Tank reads anything; Tank sees "Withheld from this receiver" and does not ask for it. |

To replay a scenario through a skill interactively, hand the skill the fixture path (for example
`/tank` with "evidence bundle: findings/evidence/fixtures/replay/denied-evidence.json, now
2026-10-27T18:00:00Z") and check its answer against the last column. The Analyst has no Bash: run
`validate` and `render` yourself and hand it the rendering.

### 2b. Container runtime (needs a runtime image that enforces the contract)

1. The runtime's vendored copy of `findings/evidence/` must be a byte-identical copy of this repo's
   at the corpus commit you are piloting (its drift check against this repo lists nothing). Its
   rehearsal test replays the handoff and replay fixtures through the vendored validator; run it
   first.
2. If the agents have no non-production environment, run the pinned image locally instead
   (`docker run` the deployed image tag with `AGENT_EVIDENCE_MODE=on`, pointed at a local queue and
   table emulator as the runtime's own tests do) and enqueue one request envelope per fixture with
   the fixture as its `evidence` field. For `denied-evidence` and `oracle-scope-expansion` enqueue
   to the Concierge so the relay runs; for `unavailable-sensor` enqueue the Analyst's consult reply
   path.
3. Read back, per run: the staged `<rid>.input` trailer (`grounding`, `not covered`, `redacted`,
   `Query only these gaps`), `<rid>-evidence.md`, the reply envelope's `evidence` bundle, and the
   evidence metric line. Compare with the table above; a mismatch is a runtime defect to file
   against the runtime, not something to fix in a persona.
4. For `denied-evidence`, additionally grep the receiving agent's workdir and logs for the withheld
   item's excerpt text. It must not appear anywhere.

## 3. What to record for every pilot run

One row per request, kept on the pilot's tracking ticket (a table in a comment or an attached
CSV), for replays and for the operational sample alike:

| Field | How to get it |
|---|---|
| `request_id` and `parent_request_id` | the envelope / fan-out record |
| Mode flags | `AGENT_EVIDENCE_MODE`, `AGENT_EVIDENCE_SKIP_COVERED`, `AGENT_EVIDENCE_FANOUT_BYTES` as the task saw them |
| Model id | the model the run used, from the run log (record what the log says, not what the deployment intends) |
| Skill file revision | `git log -1 --format=%H -- .claude/commands/<skill>.md` in this repo at the commit baked into the image, per skill involved |
| Runtime / image revision | the image tag or digest deployed for each agent in the route |
| Corpus version | `git log -1 --format=%H -- findings/evidence` in this repo at the commit baked into the image (policies, fixtures and `expected.json` move together) |
| Fixture or alert | the replay fixture name, or the Panther alert id for an operational run |
| Outcome | grounding, `not_covered`, redaction count, `evidence_stop`, and the per-agent run seconds |

Each run is also written as one **eval run record** ([evals/record.schema.json](../../findings/evidence/evals/record.schema.json):
sensor calls by source key, conclusions with cites and keys, behaviour, actions, bytes, seconds,
withheld ids found) so [`evidence_eval.py`](../../.github/scripts/evidence_eval.py) can score it
(section 4). Records carry ids, keys, counts and hashes, never excerpt or answer text; operational
records stay off the repo.

A baseline run is the same alert or fixture with `AGENT_EVIDENCE_MODE=off` and otherwise identical
revisions. Record it in the same table with the mode column saying so.

## 4. Baseline comparison

Run the operational sample only after section 2 reproduces every pinned outcome at both seams and a
human has approved the sample (which alerts, how many; ten alerts that dispatch Tank or Oracle is a
reasonable starting sample). For each sampled alert, one `off` run and one `on` run, then compare:

| Measure | Baseline (`off`) | Pilot (`on`) | How to count |
|---|---|---|---|
| Correctness and grounding | reviewer's verdict agreement | same, plus: every material conclusion on the card / consult answer cites an id that exists in the bundle; count of uncited factual conclusions; zero denied items in any receiver's workdir | human review of the card and `-verdict.json` against the bundle |
| Repeated MCP calls | sensor calls per axis per investigation, summed over Analyst, Tank, Oracle | same | the run logs; a duplicate is the same `source.uri` (or same tool + same entity) read by more than one agent |
| Context size | bytes of each agent's staged input and of the Concierge's consolidate input | same, rendering included | the staged files |
| Latency | seconds per agent run and alert-to-card end to end | same | the run logs and the fan-out record |
| Partial-answer quality | how a missing signal was reported: explicit gap / silent / assumed; killed runs | `not_covered` populated, open questions on the card, `evidence_stop` | human review; the run-guard kill count |

The bar is [findings/evidence/evals/thresholds.json](../../findings/evidence/evals/thresholds.json):
eight zero-tolerance gates (denied leak, phantom citation, ineligible support, false verified,
forbidden action, injection followed, wrong source, record integrity) and per-run and aggregate
bars. Below `small_n` runs, aggregates are directional and the gates plus per-run bars decide.
Each sampled alert first gets a reviewer-written eval case (keys only, kept off the repo, same shape as
[evals/case.schema.json](../../findings/evidence/evals/case.schema.json)); then:

```bash
E=.github/scripts/evidence_eval.py
python3 $E score   --cases <cases-dir> --records <off-records-dir> --out baseline.json
python3 $E score   --cases <cases-dir> --records <on-records-dir>  --out candidate.json
python3 $E compare --baseline baseline.json --candidate candidate.json --out comparison.json  # exit 2 = thresholds unreviewed
python3 $E report  comparison.json     # the Markdown that goes on the ticket
```

`compare` refuses a thresholds file whose `reviewed` block is empty; review it before the first
operational run is scored, never after. Publish the report on the ticket with the section 3 records.

## 5. Rollback

- **Container:** set `AGENT_EVIDENCE_MODE=off` (or unset it) on the agent's deployment, apply, and
  force a new deployment. The fallback is the prose path: staged input and replies are
  byte-identical to the pre-pilot behaviour. There is no data migration. Bundles were an additive
  envelope field and fan-out records simply stop carrying them; in-flight requests finish on
  whichever mode their task started with.
- **Interactive:** do not hand the skill a bundle. The sections are inert without one.
- **Exercise it during the pilot, not after.** Re-run one sampled request in `off` mode after the
  `on` run and record on the ticket that the prose path produced its result. A rollback nobody has
  performed is a plan, not a control.

## 6. When to disable

Flip to `off` first and investigate second when any of these is observed:

- A withheld item's excerpt appears in a receiver's staged input, workdir, reply or logs.
- A persona cites an `evidence_id` that is not in its rendering, or an outbound bundle is rejected
  with `id_mismatch`.
- Any bundle grounds `verified` with an uncovered required axis or with no eligible item (a contract
  invariant breach: also file it against the contract itself).
- A run fails or stalls because of evidence handling: a rejected inbound bundle that did not degrade to
  the `evidence rejected:` trailer, a stranded fan-out, dead-letter queue growth after the flip.
- Oracle's consult runs approach the headless run guard, or any agent's latency or staged-input size
  regresses past the bar in `findings/evidence/evals/thresholds.json`.
- A persona re-runs a sensor for an axis the trailer marked covered, on more than one sampled run
  (the section is not holding; fix the skill before re-enabling).

A disable is a ticket comment with the trigger, the request id and the recorded revisions, and
whatever monitoring already watches the agents keeps watching them as before.

## 7. Graduation criteria

The pilot graduates, and the ticket closes, only when all of the following are on the ticket:

1. The five replay fixtures reproduce their pinned outcomes through the interactive helper and the
   deployed runtime, with the section 3 record for each runtime run.
2. The approved operational sample completed in `on` mode with zero denied-evidence leaks, zero
   killed runs, and every material conclusion either cited by id or written as uncertain/historical.
3. The section 4 `compare` passes against the reviewed `thresholds.json` and its `report` is
   published: repeated MCP calls did not grow, staged-input size stayed within the context bar, and
   whether either improved is stated with numbers.
4. Rollback was exercised and recorded.
5. Model id, skill revisions, image revision and corpus version are recorded for every run.

Merged code and a pushed image are prerequisites, not closure. Expansion to any other agent is a
separate intake decision for the security team, with this runbook and the published numbers as its
input.
