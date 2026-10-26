---
schema_version: 1
id: 2026-06-08-cypher-leaked-aws-key-9d4e1a
agent: cypher
timestamp: "2026-06-08T15:05:00Z"
severity: high
domain: 8 — Software Development Security
subject: github:your-org/analytics-sandbox:config/loader.py
owner: unknown
status: open
evidence:
  - system: aikido
    url: https://app.aikido.dev/repositories/EXAMPLE/issues/secret-EXAMPLE
    note: Aikido secrets scanner flagged a long-lived AWS access key id + secret committed in plaintext
  - system: github
    url: https://github.com/your-org/analytics-sandbox/blob/EXAMPLE/config/loader.py
    note: Key committed to a low-visibility-but-org-readable sandbox repo; present in history, not just HEAD
suggested_next: [merovingian, john-wick]
---

## What

A Cypher secrets sweep (Aikido) surfaced a **long-lived AWS access key** (access key id + secret)
committed in **plaintext** to `config/loader.py` in the `analytics-sandbox` repo. The key is in
the repo's git history, not just the current HEAD, so it is exposed to anyone with org read access
and would survive a single deleting commit. The committing identity and the key's IAM permissions
are not yet resolved (`owner: unknown`).

## Why it matters

A leaked AWS credential is a classic initial-access vector. Until the key is rotated and its IAM
scope is understood, it must be treated as live: anyone who has cloned or browsed the repo could
hold it. This is the seed of a multi-agent containment cascade — the blast radius (what data/
infrastructure the key reaches) and whether it has been *used* are both open questions that other
agents own.

## Recommended action

Per [findings/HANDOFF_PROTOCOL.md](../HANDOFF_PROTOCOL.md) **row 4 — leaked secret in source code**,
this finding's emitter-set `suggested_next` is `[merovingian, john-wick]`:

- **Cypher → Merovingian** (data-classification blast radius): what data could this key reach? Is it
  scoped to a sandbox bucket or to regulated customer data?
- **Cypher → John Wick** (containment): if the key looks used, contain — rotate/revoke per the IR
  runbook. *Human-gated* — John Wick is consequential, so Steve's orchestrator stages `/john-wick`
  rather than auto-running it.
- **Human team:** the `analytics-sandbox` repo owner / platform team must **rotate the key and
  purge it from git history** (a deleting commit is not enough). `suggested_next` is agent→agent
  only; rotation is named here per the protocol's human-team rule.

> Note: this is the **seeded synthetic finding for the end-to-end kill-chain rehearsal**. The repo,
> the file path, the Aikido/GitHub URLs, and the key itself are illustrative — there is no real
> leaked credential. It lives in `examples/` so the live ledger/digest ignores it; rehearse it
> directly with
> `/security-steve findings/examples/2026-06-08-cypher-leaked-aws-key-9d4e1a.md` and watch the
> row-4 cascade: Merovingian auto-runs (low blast radius), John Wick is **staged** for approval.
