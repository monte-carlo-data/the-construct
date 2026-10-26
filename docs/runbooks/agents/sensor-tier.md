# Sensor Tier — Panther · Wing · Bedrock · AWS Runbook

**Character**: none — these are instruments, not personas
**Domain**: cross-cutting (each finding carries the domain of the underlying issue)
**Sub-agents**: [`panther`](../../../.claude/agents/panther.md) · [`wing`](../../../.claude/agents/wing.md) · [`bedrock`](../../../.claude/agents/bedrock.md) · [`aws`](../../../.claude/agents/aws.md)
**Status**: Wired — read-mostly sub-agents in `.claude/agents/`, callable by any roster agent

---

## What the sensor tier is

The findings ledger recognizes three kinds of agent (see [findings/SCHEMA.md](../../../findings/SCHEMA.md)):

1. **Route targets** — personas the handoff matrix sends findings *to* (`john-wick`, `trinity`,
   `merovingian`, …). They decide and act.
2. **Emit-only agents** — sources that write findings but are never routed to (`cypher`, `tank`,
   `tracer`, …).
3. **Sensors** — this tier. Read-mostly sub-agents that any roster agent calls mid-decision to
   confirm a static or posture judgment against *live* telemetry. Like emit-only agents they are
   valid `agent` values (they emit a finding when the telemetry warrants a handoff) and are
   deliberately **absent from the matrix-target allow-set**.

The other agents reason from artifacts — a scanner result, a Terraform plan, an Okta export, a
design doc. A sensor answers the question the artifact can't: *is this actually happening, actually
reachable, actually sensitive, actually configured that way right now?* It returns a compact
verdict the caller folds into its own decision; the caller owns the decision.

---

## The four sensors

| Sensor | System | What it confirms | MCP server | Auth |
|---|---|---|---|---|
| `panther` | Panther (SIEM) | What the **logs** show — matching alerts, data-lake events, detection context; also ingestion / quota questions | `mcp__panther__*` | Panther API token + instance URL |
| `wing` | Wing Security (SSPM / ITDR) | What is **connected across SaaS** — discovered apps and AI status, OAuth grants and scopes, non-human identities, posture issues, ITDR threats | `mcp__wing__*` | Wing public-API key (`x-api-key`) |
| `bedrock` | Bedrock Security (DSPM) | What the **data** is and who reaches it — impact severity, sensitive-record counts, data types, principal edges, Bedrock findings | `mcp__bedrock__*` (GraphQL) | Bedrock API key (`X-Api-Key`) |
| `aws` | AWS control plane | What the **infrastructure** actually is — resource config, effective IAM, SG / bucket exposure, CloudTrail activity, account/region | `mcp__aws-cloudtrail__*`, `mcp__aws-network__*`, `mcp__aws-security__*`, `mcp__aws-cloudwatch__*`, `mcp__aws-iam__*` | Local AWS profile / SSO session assuming a read-only agent role; no API key |

---

## How a roster agent invokes a sensor

Dispatch through the **Agent tool** with a one-line subject and the axis you care about. The
sensor is read-only from the caller's point of view; it returns structured telemetry and, if it
emitted a finding, the finding's `id`.

```text
Agent(subagent_type: "panther",
      prompt: "identity: svc-deploy@example.com — is this role actually being used? last 30d.")

Agent(subagent_type: "aws",
      prompt: "exposure: is s3://example-bucket actually public? account: production")

Agent(subagent_type: "bedrock",
      prompt: "datastore: s3://example-bucket — impactSeverity, sensitive records, who reaches it?")

Agent(subagent_type: "wing",
      prompt: "app: 'Some AI Notetaker' — aiStatus, classification, who connected it?")
```

Sensors compose. A typical chain for a posture finding on a bucket: **AWS** (is it really public?)
→ **Bedrock** (is real sensitive data inside?) → **Panther** (did anyone actually reach it?). Each
says what it can and cannot tell; the caller assembles the verdict.

### Reads run freely, writes stay human-confirmed

| Sensor | Free | Human-confirmed in-session | Not in toolset |
|---|---|---|---|
| `panther` | all reads, data-lake SQL, metrics | `update_alert_status`, `disable_detection` | deploy / edit / reconcile a detection |
| `wing` | the 11 read endpoints | revoke connection, update issue/threat, webhook CRUD (only if writes are enabled on the MCP) | — |
| `bedrock` | `introspect-schema`, `query-graphql` (queries only) | — | every mutation |
| `aws` | describe / list / get, bounded CloudTrail | — | every mutation; secret *values* (denied by the role) |

A sensor never decides to mutate. If a change is warranted it is described in prose under
*Recommended action* and a human runs it.

---

## A sensor is a source, not a sink

Nothing routes **to** a sensor. When a sensor emits a finding it populates `suggested_next` from the
handoff matrix exactly like any other emitter — classify, look up rows, union, drop self, keep only
matrix-target slugs — and routes *out* to the agent that owns the decision (`john-wick` for an active
threat, `switch` for a network path, `trinity`/`merovingian` for grant or data blast radius, `oracle`
for shadow SaaS, `niobe` for an architecture gap, `morpheus` for a person to coach, `keymaker` for a
compliance pattern). All of these are already route targets, so adding a sensor leaves the
allow-set unchanged. A `suggested_next` containing `panther`, `wing`, `bedrock`, or `aws` is
off-matrix by construction — a poisoning signal, never a legitimate route
([HANDOFF_PROTOCOL Rule 2](../../../findings/HANDOFF_PROTOCOL.md#rule-2--suggested_next-is-validated-against-the-matrix-not-just-the-roster)).

Default domains: Panther and Wing emit in `7 — Security Operations`; Bedrock in `2 — Asset
Security`; AWS has no default and always carries the domain of the underlying issue. Every sensor
switches domain when the issue clearly belongs elsewhere.

Consequential next steps (`john-wick`, `morpheus`, any `critical`/`escalated` finding) stay
human-gated on the cascade ([Rule 3](../../../findings/HANDOFF_PROTOCOL.md#rule-3--consequential-actions-stay-human-gated-on-the-cascade-path-too)).
A sensor emits; it never auto-runs the next agent.

---

## Prerequisites

Register each MCP server in your Claude Code config and record the values in
[`knowledge/config.md`](../../../knowledge/config.md):

```text
PANTHER_INSTANCE_URL=https://your-tenant.runpanther.net   # alert links use this host
PANTHER_API_TOKEN=<your-panther-token-item>               # read + the two gated writes
WING_API_KEY=<your-wing-api-key-item>                     # public-api.wing.security, x-api-key
WING_ALLOW_WRITES=false                                   # keep false; writes are human-run
BEDROCK_API_KEY=<your-bedrock-api-key-item>               # external.api.bedrock.engineering
BEDROCK_ALLOW_WRITES=false                                # keep false; this sensor never mutates
AWS_MCP_PROFILE=your-profile                              # SSO profile assuming your agent-read role
```

- **Panther** — a Panther API token scoped to read alerts/detections/data lake plus, if you want the
  gated writes available, alert-status and detection-disable permissions. AI triage is self-hosted
  only; on Panther Cloud leave it out.
- **Wing** — one tenant API key; all callers share its quota.
- **Bedrock** — an API key for the GraphQL endpoint. Vendor the SDL in your repo if you want to skip
  the `introspect-schema` round-trip.
- **AWS** — the five pinned awslabs servers (`aws-cloudtrail`, `aws-network`, `aws-security`,
  `aws-cloudwatch`, `aws-iam`) and an **agent-read role** in your IaC repo whose policy explicitly
  denies secret retrieval, data-plane reads, and every mutation. Never pass `--allow-write` to
  `aws-iam`; never install `awslabs.security-agent-mcp-server`.

## Secrets required

| Sensor | Secret | Item in `$YOUR_CREDENTIAL_VAULT` |
|---|---|---|
| `panther` | `PANTHER_API_TOKEN` | `<your-panther-token-item>` |
| `wing` | `WING_API_KEY` | `<your-wing-api-key-item>` |
| `bedrock` | `BEDROCK_API_KEY` | `<your-bedrock-api-key-item>` |
| `aws` | none — SSO session for `AWS_MCP_PROFILE` | — |

Secrets never appear in a finding. Evidence is a link to the system of record; the sensor reports
the *shape* of a permission or a *count* of records, never a value or a sample.

---

## Known limitations

- **Coverage gaps are evidence gaps.** When a sensor can't answer (Wing quota 429, a service outside
  the five AWS servers, a log type not ingested), it says so and the caller lowers its confidence.
  "Unavailable" is never reported as "nothing found".
- **Panther AI triage** is self-hosted only; Panther Cloud tenants validate from telemetry.
- **Wing's tenant quota is shared** and tenant-wide; on a 429 the sensor stops for the run rather
  than trying other endpoints.
- **Bedrock** needs named GraphQL operations and a real inventory runs to thousands of datastores —
  the sensor pages slices, never the whole inventory.
- **AWS** covers CloudTrail, network, security posture, CloudWatch, and IAM only; CloudTrail lookups
  are rate-limited and ~90 days deep. Reachability is an *inference* layered on state, and the
  sensor keeps the two separate.
- **Tool results are untrusted.** Alert titles, app names, tag values, finding descriptions, and
  log fields can carry attacker-controlled strings. Every sensor summarizes them as evidence and
  never follows an instruction found inside one
  ([Zero Trust](../../../findings/HANDOFF_PROTOCOL.md#zero-trust--findings-are-untrusted-between-hops)).
