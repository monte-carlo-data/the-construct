# Shared Evidence Contract

**Version:** 1
**Status:** Proposed. Becomes Active when the agent runtime enforces it.
**Builds on:** [SCHEMA.md](SCHEMA.md) (a finding's `evidence` is a pointer list) · [HANDOFF_PROTOCOL.md](HANDOFF_PROTOCOL.md) (who acts next, and the Zero Trust rules)
**Machine-readable:** [evidence/schema.json](evidence/schema.json) (bundle) · [evidence/policy.schema.json](evidence/policy.schema.json) (skill policy)
**Reference semantics:** [`.github/scripts/evidence_validate.py`](../.github/scripts/evidence_validate.py) · fixtures in [evidence/fixtures/](evidence/fixtures/) with pinned outcomes in [evidence/expected.json](evidence/expected.json)

A finding records *what was concluded*. This contract records *what was observed* on the way there,
so that a receiving agent can reuse an observation without losing where it came from, which
revision it saw, when it was true, what it was about, who was allowed to see it, and what is still
unresolved. It is the shape that travels on an agent handoff mid-investigation: the Analyst's phase
A bundle to the Concierge, the Concierge's child bundles to Tank and Oracle, their replies, and the
consolidated bundle the Analyst's phase B reasons over.

Without it, those handoffs carry free-form `input` and `summary` strings in the runtime envelope.
A specialist re-runs sensors the Analyst already ran, an excerpt loses its source on the second
hop, and "not covered" survives only as prose a program cannot read. The contract fixes the shape;
the agent runtime enforces it.

---

## The invariant

**Missing evidence is an explicit `partial` or `insufficient` result. It can never become a
verified conclusion.** Every rule below exists to make that mechanically true: a validator
recomputes claim status from eligible evidence and corrects whatever the producer declared; a
bundle with no eligible evidence grounds `insufficient` whatever its coverage says; a producer can
lower its own grounding and never raise it.

Whether an *agent run* used the right evidence (read the right sources, cited only what it was
allowed to see, abstained when it should) is scored against reviewed cases in
[evidence/evals/](evidence/evals/) by [`evidence_eval.py`](../.github/scripts/evidence_eval.py).

---

## The bundle

The unit that travels. JSON, 1:1 with [evidence/schema.json](evidence/schema.json). Additive fields
are allowed within a major version; readers ignore what they do not know.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `contract_version` | integer | yes | `1`. An unsupported version rejects the whole bundle. |
| `bundle_id` | string | yes | Producer-assigned, unique per emission. |
| `producer` | agent slug | yes | Who emitted this bundle. |
| `receiver` | agent slug | yes | Who it is addressed to. `allowed_receivers` is checked against this. |
| `created_at` | timestamp | yes | Emission time. |
| `request_id`, `parent_request_id` | string | no | The runtime envelope ids the bundle rides on (correlation stays the runtime's job). |
| `items` | list of items | yes | The observations. May be empty, in which case nothing can be grounded. |
| `claims` | list of claims | yes | Statements the producer makes, each citing items for and against. |
| `questions` | list of questions | yes | What the producer could not settle and wants the receiver to answer. |
| `hops` | list of hops | yes | Provenance chain: who emitted or forwarded the bundle, in order. |
| `coverage` | object | yes | The producer's own ceiling (`complete` / `partial` / `insufficient`) and the axes it could not cover. |
| `redactions` | list | no | Items withheld on a hop, by id and reason. The receiver sees that something was withheld, never what. |

Timestamps are ISO-8601 UTC with second precision and an explicit `Z`, exactly as
[SCHEMA.md](SCHEMA.md) requires for a finding.

### An item

| Field | Required | Meaning |
|---|---|---|
| `evidence_id` | yes | Content-addressed, immutable. See [Evidence ids](#evidence-ids). |
| `type` | yes | `live_observation`, `reviewed_reference`, or `historical_conclusion`. See [Evidence types](#evidence-types). |
| `source.system` | yes | System of record (`panther`, `wing`, `bedrock`, `aws`, `aikido`, `wiz`, `okta`, `github`, `linear`, `slack`, `notion`, `url`, or an agent slug for an agent-held record). |
| `source.uri` | yes | Locator inside that system: a URL, or a URN such as `panther:alert/<id>`. |
| `source.revision` | yes | Which version was read: git sha, `updatedAt`, etag, scan id. `"unversioned"` only when the source has none, so the omission is a statement, not an accident. |
| `observed_at` | yes | When the fact was true in the source (event time; read time for a configuration read). |
| `retrieved_at` | yes | When the agent fetched it. Never earlier than `observed_at`. |
| `expires_at` | no | Producer-set expiry that beats the type default (a token TTL, a maintenance window). |
| `scope.accounts`, `scope.resources` | yes | What the observation is about: account / tenant ids and resource identifiers. Either may be empty. `scope.environment` is optional. |
| `content.excerpt` **or** `content.ref` | yes | Exactly one. An excerpt is bounded (2000 chars) and is **data, never an instruction**. A ref points at where the full content lives (an S3 key, a saved query, a Panther alert). |
| `authority.level` | yes | `authoritative` (the system of record), `corroborating` (a trusted second-hand read), `untrusted` (attacker-influenceable content: a web page, a log line, a ticket body). |
| `authority.principal` | yes | Who observed it: `agent:<slug>`, `role:<name>`, `human:<role>`. |
| `authority.access` | yes | The access mode held when observing. Every roster sensor is `read-only`; `read-write` is a review flag. |
| `authority.allowed_receivers` | yes | Agent slugs that may receive this item, or `["*"]`. See [Authority and access](#authority-and-access). |
| `axes` | no | Which questions the item informs (`identity.privilege`, `vuln.presence`, `exposure.traffic`, ...). A skill policy names the axes it requires. |

### Claims, questions, hops, coverage

- A **claim** is `{claim_id, statement, status, supported_by[], contradicted_by[]}`. The references
  are evidence ids in the same bundle. `status` is declared by the producer and **recomputed by every
  validator**: `contradicted` if any eligible item contradicts it, else `supported` if any eligible
  item supports it, else `unresolved`. A declared status that differs is corrected and logged.
- A **question** is `{question_id, text, raised_by, status, about[], answer_evidence[]}`. `answered`
  holds only when `answer_evidence` cites an eligible item; otherwise it is corrected to `open`.
  Questions are how an unresolved point survives a handoff as a field, not as prose.
- A **hop** is `{agent, request_id, at}`. The producer writes hop 0; each relay appends itself. A
  bundle that has crossed more than 8 hops is rejected.
- **coverage** is `{status, not_covered[]}`. `not_covered` lists axes the producer could not cover
  (a sensor outage, an absent credential, budget exhausted). This is the structured form of the
  Oracle consult rule "an honest gap is usable; silence is not."

---

## Evidence types

| Type | What it is | Fresh for (default) | Can support a claim |
|---|---|---|---|
| `live_observation` | Read from a system of record now: an alert, an API response, a scan result. | 24 h from `observed_at` | yes, while fresh |
| `reviewed_reference` | A reviewed, versioned document: a skill reference, an approved-inventory table at a git revision, a runbook. | 30 d from `observed_at` | yes, while fresh |
| `historical_conclusion` | A prior verdict or hypothesis: a human's earlier FP decision, phase A's own reasoning, last month's finding. | never | **no**. It informs a prior and is carried as context; a claim supported only by historical items is `unresolved` and flagged. |

This is the separation of historical hypotheses from current facts. The Analyst's `_analyst_prior_verdict`
is a `historical_conclusion` item; the Analyst's phase A hypothesis is a `claim` with status
`unresolved`, not an item at all, because nothing was observed.

---

## Evidence ids

`evidence_id = "ev-" + sha256(canonical_json({type, source, observed_at, scope, content}))[:16]`

where `canonical_json` sorts keys, uses no whitespace, keeps non-ASCII, and `scope.accounts` /
`scope.resources` are sorted and de-duplicated first. The id is **content-addressed**: the same
observation yields the same id wherever it is produced, and a relay that edits an excerpt and keeps
the id is caught (`id_mismatch`, the bundle is rejected). `retrieved_at`, `authority` and `axes` are
deliberately outside the identity: two retrievals of one fact are one item.

Ids are minted by the **producer's runtime** (`evidence_validate.py mint`), never typed by the model;
a skill emits items with `evidence_id: ""` and the runtime fills them in. A new item that the
skill's own claims or questions cite takes a **local handle** instead (`"evidence_id": "new:alert"`),
and the claim cites `"new:alert"`; `mint` rewrites every reference to a handle held by exactly one
item to the minted id. A duplicated or unknown handle is left alone and rejected as an unknown
evidence id. Handles exist only before `mint`; no bundle on the wire carries one. Once minted an id never
changes, and every hop re-verifies it. **Evidence ids survive every handoff**: a relay copies items
unchanged, a reply carries forward every item it cites, and a merge keeps the first occurrence.

---

## Validation

One bundle, one receiver, one instant (`now`). The reference implementation is `validate()` in
`evidence_validate.py`; the runtime must produce the same outcome on every fixture.

| Step | Checks | On failure |
|---|---|---|
| 1 Structure | required fields, enums, timestamp shape, exactly one of excerpt/ref, references resolve to items in the bundle, no future `observed_at`, `retrieved_at` ≥ `observed_at`; the skill policy if one is supplied | **rejected** `malformed` (all errors listed) or `unsupported_version` |
| 2 Budgets | see [Budgets](#budgets) | **rejected** `oversized` or `hop_budget` |
| 3 Integrity | every `evidence_id` equals its content hash | **rejected** `id_mismatch` |
| 4 Item state | per item: `denied` (receiver not allowed), else `historical`, else `expired` (past `expires_at`), else `stale` (past freshness), else `fresh` | never a rejection |
| 5 Claims and questions | status recomputed from **eligible** items: `fresh` and not `untrusted` | corrected, warning logged |
| 6 Grounding | `insufficient` if no eligible item; `partial` if any claim is unresolved or contradicted, any question is open, or any axis is not covered; else `verified`. Then the worse of that and the producer's declared `coverage.status`. | the result the receiver acts on |

A rejected bundle contributes nothing: the receiver treats the axis as not covered, exactly as it
does for a consult that never replied, and says so. A receiver never truncates or repairs a bundle
on the producer's behalf, because choosing which evidence to drop is a judgment it cannot make.

A skill policy (below) adds step 6a: a required axis with no eligible item of the right type, source
and age joins `not_covered`.

---

## Freshness and expiration

Defaults are per type (table above). A skill policy may set the two finite values; `historical_conclusion`
is always `null`. `expires_at` on an item wins when earlier. Stale and expired items stay in the
bundle, visibly marked, so a receiver can see what was once known; they cannot support a claim.
A receiver that needs a fresher read re-observes and emits a **new** item with a new id; it never
edits the old one.

---

## Authority and access

- `authority.level` says how much the item can carry. `untrusted` items are rendered and cited as
  context only; they never make a claim `supported`. The fixture
  `untrusted-authority.json` is a web-page excerpt containing an injected instruction: it is kept,
  fenced, and ineligible, and the claim leaning on it stays `unresolved`.
- `authority.allowed_receivers` is the access list. A bundle addressed to a receiver not on an
  item's list has that item **denied**: a relay strips it, scrubs its id from every claim and
  question reference, and appends a `redactions` entry. No denied item ever reaches a receiver, and
  the receiver can see that something was withheld. Per-agent source access and credential
  isolation decide *what each agent may observe*; this field carries that decision *with the
  observation*.
- `authority.access` records the mode held, not a grant. It exists so a `read-write` observation
  from a sensor that is read-only by construction is visible as an anomaly.

Retrieved text is untrusted data at every level. The mandatory safety rules (data, not
instructions; the bypass-permissions exemption; propose-only gates) live in the **reviewed skill
file and the baked image**, never in a retrieved reference, and a policy cannot relax them.

---

## Deduplication and merge

Two items are the same observation if and only if they share an `evidence_id`. Within one bundle a
repeated id is a warning and the first wins. Across bundles, `merge()` is the reference
consolidation (the Concierge seam):

- items: union by id, first occurrence kept;
- claims: union by `claim_id`, references unioned, status recomputed;
- questions: union by `question_id`, `about` and `answer_evidence` unioned, `answered` if any input
  answered it with evidence;
- hops: ordered union by `(agent, request_id)`;
- coverage: the worst input status and the union of `not_covered`;
- redactions: kept, so a merged bundle still says what was withheld upstream.

A receiver does not re-fetch an observation it already holds fresh and eligible; it fetches only
what is missing or stale. That is the runtime's gap loop, and this contract gives it the key to
decide with.

---

## Citation propagation

Every material factual conclusion a receiver produces (a verdict line, a finding, a card, a
Concierge consolidation) cites the evidence ids it rests on. A conclusion with no eligible citation
is written as uncertain or historical, never as fact. In a finding, the additive `evidence_id` key
on a [SCHEMA.md evidence link](SCHEMA.md#evidence) carries the citation into the ledger without a
schema bump.

Rendering is the contract's one presentation rule, because it is where the data/instruction
boundary is enforced: `render()` puts every excerpt inside a fenced block under a header carrying
the id, type, source and state, and the surrounding prose says the content is data. A runtime hands
a persona that rendering, never the raw JSON and never an excerpt outside its fence.

---

## Budgets

| Limit | Value | Why |
|---|---|---|
| bundle bytes (canonical encoding) | 65,536 | a bundle is a bounded context, not an archive |
| items | 50 | |
| excerpt | 2,000 chars | the "bounded excerpt or reference" rule; anything larger is a `ref` |
| claims, questions | 50 each | |
| hops | 8 | a cycle or an unbounded relay chain is a runtime defect, not a longer investigation |
| clock skew | 300 s | an `observed_at` further in the future is malformed |

Over any limit the bundle is rejected. The runtime's tool-call, result-count and elapsed-time
budgets are its own; they bound how a bundle is *built*, this table bounds what may *travel*.

---

## Skill policy

A skill declares what it requires before it may conclude, as a JSON file next to the skill (1:1
with [evidence/policy.schema.json](evidence/policy.schema.json)). The runtime applies it at the
receiving seam; interactively, `evidence_validate.py validate --policy` applies it.

```json
{
  "contract_version": 1,
  "skill": "tank",
  "required": [
    {"axis": "vuln.presence", "types": ["live_observation", "reviewed_reference"],
     "sources": ["aikido", "wiz", "github"], "max_age_seconds": 86400}
  ],
  "freshness": {"live_observation": 86400, "reviewed_reference": 2592000, "historical_conclusion": null},
  "insufficient_evidence": "partial"
}
```

- `required[].axis` names an axis the skill's verdict rests on; `types`, `sources` and
  `max_age_seconds` say what satisfies it. `sources` is the skill's **trusted authority** for that
  axis: Aikido is authoritative for a vuln's presence, Panther for traffic, Wing for a SaaS grant.
- `freshness` overrides the two finite defaults for this skill.
- `insufficient_evidence` has exactly one legal value, `partial`. A policy that says anything else
  is malformed. A skill with an unmet required axis answers with the axis in `not_covered` and a
  verdict that says so, which is the Oracle consult rule written down.

The pilot policies are in [evidence/policies/](evidence/policies/) (`analyst.json`, `tank.json`,
`oracle.json`). How each pilot skill uses its policy is the `Evidence contract` section of
[`/analyst`](../.claude/commands/analyst.md), [`/tank`](../.claude/commands/tank.md) and
[`/oracle`](../.claude/commands/oracle.md); operating the pilot is
[docs/runbooks/evidence-pilot.md](../docs/runbooks/evidence-pilot.md).

---

## Where the contract applies

| Seam | Owner | What happens |
|---|---|---|
| **Interactive invocation** (a human runs `/tank`, `/oracle`, `/analyst` in Claude Code) | the security repo | The skill may be handed a bundle path; it runs `evidence_validate.py validate --receiver <skill> --policy <policy>`, reads the rendering, and emits its own items with empty ids for `mint`. Nothing in the skill's safety rules changes. |
| **Consumer input** (the runtime stages a request for an agent) | the agent runtime | If the envelope carries a bundle, validate it for the receiving agent, strip denied items, render, and stage the rendering beside the input. A rejected bundle is staged as a one-line "evidence rejected: <reasons>" so the persona reports the gap. |
| **Concierge consolidation** (the runtime builds the consolidate input) | the agent runtime | Child bundles are relayed from the parent with `relay()`; replies are validated and merged with `merge()`; the consolidated bundle is rendered into the consolidate input and travels to the parent's reply. |
| **Analyst phase B** (the runtime hands the consult replies back) | the agent runtime | The replies file carries the consolidated bundle's rendering, with phase A's hypothesis as an unresolved claim and its questions as questions. STEP 3 cites ids; a question still `open` is a gap on the card. |

The envelope itself does not change shape: a bundle rides as an additive, optional field, omitted
when absent, exactly as earlier optional envelope fields were added.

---

## Worked example: Analyst → Concierge → Tank / Oracle

The fixtures under [evidence/fixtures/handoff/](evidence/fixtures/handoff/) are one investigation,
generated by [`evidence_fixtures.py`](../.github/scripts/evidence_fixtures.py) so every derived
step is produced by the reference functions:

| File | Step | What it shows |
|---|---|---|
| `01-analyst-to-concierge.json` | Analyst phase A emits: Panther, Wing, Bedrock items (fresh), a prior human verdict (historical), claim `c1` unresolved, questions `q1` (is the IP ours?) and `q2` (does the CVE apply?), `identity.privilege` not covered. | A hypothesis is a claim, not evidence. A gap is a field. |
| `02a-concierge-to-tank.json` | `relay()` to Tank. | Hop appended; all four ids intact. With Tank's policy, `vuln.presence` is also not covered yet. |
| `02b-concierge-to-oracle.json` | `relay()` to Oracle. | The Bedrock item is not cleared for Oracle: stripped, its id scrubbed from references, a redaction recorded. |
| `03a-tank-reply.json` | Tank adds an Aikido item, answers `q2`, adds claim `c2` supported. | New evidence gets a new id; the carried items keep theirs. |
| `03b-oracle-reply.json` | Oracle adds an AWS EIP item, answers `q1`, declares `exposure.external_scan` not covered. | A targeted consult that says what it could not check. |
| `04-concierge-consolidated.json` | `merge()` of 01, 03a, 03b. | All six ids present; `q1`, `q2` answered; `c1` still unresolved; gaps unioned; grounding `partial`. |

The pinned outcomes in [evidence/expected.json](evidence/expected.json) are the acceptance test:
source references and unresolved questions survive end to end, and the consolidated result is
`partial` because `c1` was never supported and one axis was never covered.

---

## Repo ownership

| Concern | Owner | Where |
|---|---|---|
| The contract: this document, both JSON schemas, the fixtures, the pinned outcomes, the reference validator, skill policies | **the security repo** (this one) | `findings/EVIDENCE.md`, `findings/evidence/`, `.github/scripts/evidence_validate.py`, `.github/scripts/evidence_fixtures.py` |
| Runtime enforcement: validation at the consumer / Concierge / Analyst seams, retrieval and the gap loop, byte/tool/hop/time budgets, metrics, opt-in rollout and fallback | **the agent runtime** | the runtime's own repository; it must replay `findings/evidence/expected.json` from this repo's main branch in its drift test |
| Engineering SDLC agents (`rama-kandra` … `twins`) | call security skills read-only; **never modify** a skill, a policy, this contract or the ledger | [SCHEMA.md → Engineering SDLC agents](SCHEMA.md#agent-roster--agent--suggested_next-vocabulary) |

A contract change is a PR here first (fixtures and `expected.json` regenerated, the diff reviewed),
then a runtime change there. The runtime never carries a second definition of the shape.

---

## Versioning

Additive changes (a new optional field, a new `source.system` value, a new axis name) stay within
version 1 and do not change ids, because the identity fields are fixed. A breaking change (a removed
or renamed field, a changed identity, a changed hash) bumps `contract_version` to 2; a validator
rejects any version it does not support rather than guessing.

## Non-goals

- Transport, correlation, retries, dedup leases and reply routing stay the runtime's.
- Semantic retrieval, ranking, a vector store or any new service: not assumed. Exact id and metadata
  filtering come first.
- The findings ledger's own shape is unchanged; a finding cites evidence ids, it does not embed bundles.
