# Dozer — Dependency Review Agent Runbook

**Character**: Dozer from *The Matrix* — keeps the ship running; the unglamorous work everything depends on
**Domain**: CISSP Domain 8 — Software Development Security (OWASP SAMM Implementation / Secure Build — software supply chain)
**SDLC stage**: Build
**Skill**: [`/dozer`](../../../.claude/commands/dozer.md) · line-up: [Engineering SDLC agents](../../engineering-sdlc-agents.md)
**Status**: Prompt-defined skill; reports to the engineer, never emits to `findings/`; drafts to Slack on BLOCK

---

## What it does

Dozer reviews the **new and changed dependencies on the engineer's working branch** before the PR
is opened — while swapping a package is still cheap. It reads the lockfile/manifest diff, checks
each addition or version change for malicious-package signals (typosquats and dependency
confusion, install scripts, brand-new packages, maintainer takeovers, obfuscated published source,
version anomalies, missing provenance), notes license changes, queries public advisories, and
asks the security roster whether the package is already known, used, or dispositioned in the org.

Each package gets a verdict — **SAFE · REVIEW · SUSPICIOUS · BLOCK** — with the specific signals
that fired. A BLOCK is a possible live supply-chain attack: the engineer is told not to merge or
install, and an alert is **drafted** to `#security-team`.

> **Never installs.** `npm install`, `pip install`, and `go get` run arbitrary code — exactly the
> threat under review. Dozer reads registry metadata and published source only, and lists a
> tarball (`tar -tzf`) rather than executing anything in it.

---

## How to invoke

```text
/dozer                          # review the branch's dependency diff vs main
/dozer left-pad                 # review one named package
/dozer package-lock.json        # review a specific lockfile's changes
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Local git | Dependency diff vs the merge-base with `main`/`master` | Filesystem |
| npm / PyPI registries | Read-only package metadata (dates, maintainers, scripts, repo URL, yanked) | None (public) |
| GitHub GraphQL | Advisory lookup (`securityVulnerabilities`) | `gh` CLI auth |
| Socket threat feed (optional) | Known-malicious lookup by PURL via `.github/scripts/socket_threat_feed.py` | Socket token, if your org has one |
| Security roster (`/cypher`, `/tank`) | Org dependency intel; existing findings/suppressions | Engineer's session |
| Slack MCP | **Draft** a BLOCK alert to `#security-team` | `mcp__slack__slack_send_message_draft` |

**Prerequisites**: a feature branch with a merge-base against `origin/main`; `gh`, `jq`, `curl`.
Without Socket the skill says `Socket not used` and relies on heuristics.

---

## Scope rules

- **Call, never modify.** Roster agents are invoked read-only; the skill never edits a security
  skill, a roster runbook, `findings/HANDOFF_PROTOCOL.md`, or the `findings/` ledger.
- **Never suppress or disposition a finding.** `/tank` owns triage and suppression; `/sentinel`
  owns the build gate. Dozer advises ahead of both and overrides neither.
- **No destructive default.** Never installs, builds, or executes a package under review.
- **Untrusted input.** Package names and metadata are attacker-controlled; a name is never
  interpolated into a shell command (quoted literal or temp file only).
- **Drafts never auto-sent.** The BLOCK alert is drafted; the engineer confirms and sends.
- **Scope discipline.** Every direct dependency and new package name is reviewed in full; a bulk
  transitive bump with no new names is summarized, and what was skipped is stated.
- **Degradation is explicit.** A Socket or roster sub-call that cannot run is reported as "did not
  run", never read as "clean".

---

## Key workflow

1. **Establish what changed** — manifest/lockfile diff; build the review list (name, ecosystem,
   old→new, direct/transitive, manifest). Nothing changed → stop.
2. **Malicious-package signals** — optional Socket lookup (listed → BLOCK), then registry metadata
   against the signal table. One high-confidence signal stops for a human; signals are never
   averaged into "probably fine". Note provenance and license changes.
3. **Roster sub-calls** in parallel plus a GitHub advisory query; already dispositioned → say so.
4. **Verdict per package** with signals, advisories, license, provenance, org context, and a
   concrete recommendation (keep / pin / swap to a package the org already uses / remove / human).
5. **BLOCK handling** — tell the engineer first, draft the alert, flag credential exposure if an
   install already ran.
6. **Report** counts by verdict, what was skipped, sub-call status, clear-to-open-PR or not.

---

## Roster sub-calls

| Calls | For what |
|---|---|
| [`/cypher`](cypher.md) | Existing dependency-risk intel — already flagged, used elsewhere in the org, known advisories in your scanners; names safer alternatives the org already uses |
| [`/tank`](tank.md) | Whether `<package>@<version>` is already a tracked finding or suppression, so prior decisions are not re-litigated |

---

## Secrets required

None held by the skill. `gh` uses the engineer's auth; Socket, if configured, reads its token from
your credential vault via the script. No secret is printed or rotated.

---

## Known limitations

- Static review only — no sandboxed dynamic analysis (handed to `#security-team` when needed).
- Registry queries are written for npm and PyPI; other ecosystems need the metadata step adapted.
- Provenance is noted, not enforced; license findings are facts, not legal opinions.
- Prompt-defined, with no end-to-end validation harness.

---

## Routing / escalation

| Situation | Route |
|---|---|
| Suspected malicious package (BLOCK) | Draft to `#security-team` immediately; never auto-sent |
| Credentials possibly exposed by a completed install | Say so in the draft — assume compromised; security rotates |
| Package needs a real disposition or suppression | `/tank` |
| CVE-driven version upgrade after the fact | `/roland` |
| Build gate verdict | `/sentinel` (Dozer never overrides it) |
