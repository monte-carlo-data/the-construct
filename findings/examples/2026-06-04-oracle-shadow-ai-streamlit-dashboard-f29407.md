---
schema_version: 1
id: 2026-06-04-oracle-shadow-ai-streamlit-dashboard-f29407
agent: oracle
timestamp: "2026-06-04T14:30:00Z"
severity: medium
domain: 7 — Security Operations
subject: streamlit-app:analytics-demo-example.streamlit.app
owner: jdoe@example.com
status: open
evidence:
  - system: url
    url: https://analytics-demo-example.streamlit.app
    note: Publicly reachable Streamlit dashboard, no auth gate; calls the Claude API
  - system: github
    url: https://github.com/orgs/your-org/people/jdoe
    note: Repo last pushed by this identity; deploy traced to a personal Streamlit Community Cloud account
suggested_next: [morpheus]
---

## What

During an Oracle shadow-AI / exposed-endpoint sweep, a **publicly reachable Streamlit dashboard**
(`analytics-demo-example.streamlit.app`) was found with **no authentication gate**. It is a
hackathon-era demo that calls the Claude API and renders company-branded sample analytics. The
deploy traces to an individual employee's personal Streamlit Community Cloud account, not a
reviewed deployment. The data shown is sample/demo data — no live customer data was observed — so
this is a shadow-AI / unreviewed-deployment hygiene issue, not a sensitive-data exposure.

## Why it matters

A person shipped an AI-backed, internet-exposed app outside the review path. At `medium` it isn't an
incident — but it is exactly the just-in-time coaching moment the awareness program exists for: the
employee needs to know the right way to deploy (review + your internal tools platform), and the
demo should be gated or taken down. Left alone, these accumulate into real exposure when someone
wires live data into the next one.

## Recommended action

- **Oracle → Morpheus** (`suggested_next: [morpheus]`, matrix row 6 — shadow-AI / exposed endpoint
  where a *person* is responsible): draft just-in-time, non-disciplinary awareness outreach to the
  employee to (a) take down or auth-gate the demo and (b) route any future deploy through review /
  your internal tools platform. **This hop is human-gated** — Morpheus drafts outreach to a named
  person, so Security Steve's orchestrator stages `/morpheus` rather than auto-running it.
- **Human team:** if the employee has left or this is unowned, re-route to Trinity / the platform
  team for takedown rather than awareness outreach.

> Note: this is a **reference example** seeded for orchestrator validation (the gated path). The
> Streamlit URL, the account `jdoe@example.com`, and the GitHub link are illustrative, not real. It
> lives in `examples/` so the live ledger scan ignores it; orchestrate it directly with
> `/security-steve findings/examples/2026-06-04-oracle-shadow-ai-streamlit-dashboard-f29407.md` to
> watch Steve **stage** the gated `/morpheus` hop.
