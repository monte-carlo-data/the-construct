# Sentinel — Secure Build Gate Agent Runbook

**Character**: Sentinel from *The Matrix* — the machines that hunt in the real world
**Domain**: CISSP Domain 8 — Software Development Security (OWASP SAMM Implementation / Secure Build)
**Skill**: [`/sentinel`](../../../.claude/commands/sentinel.md)
**Status**: Wired — two modes, `warn` (visible verdict, exit 0) and `block` (red check); emit-only in the findings roster

---

## What it does

Sentinel is the first roster agent that **blocks an insecure build** rather than documenting one.
Every other build-security agent (SBOM create / validate, AIBOM tooling, Cypher) *surfaces*
artifacts; your PR-review workflow / Architect are human-gated. Sentinel **gates**: a non-zero exit
+ a red PR status check when a build can't be proven clean.

It runs three fail-closed checks over a repo's CycloneDX SBOM:

1. **SBOM present** — the file exists, parses as CycloneDX, has ≥1 component.
2. **SBOM complete** — delegates to your existing `sbom_validate.py` (path-leak / secret / shape).
3. **CRITICAL ≤ threshold** — Grype over the SBOM, FAIL if CRITICAL CVEs exceed the configured count.

It reuses the proven **Syft → Grype** pipeline (Syft builds the SBOM; Grype reads CycloneDX natively)
— the same path your SBOM-create tooling (Syft) and any SBOM-scanning dashboard (Grype) run. No new
scanner. It is the **SBOM-centric** counterpart to a container-image vuln-scan workflow (which scans
built container images).

> **Fail-closed.** A missing/unparseable SBOM or an unavailable Grype binary is a gate FAILURE, never
> a silent PASS. You cannot prove a build is clean from absence of data.

---

## How to invoke

```text
/sentinel                 # gate the current repo (generate SBOM with Syft, then run the gate)
/sentinel <repo-path>     # gate another local repo
/sentinel <sbom.cdx.json> # gate an existing/downloaded CycloneDX SBOM directly
```

In CI it runs automatically via the reusable workflow on PRs (see below).

---

## CI wiring

- **Engine** — `.github/scripts/sentinel_gate.py`: the three-check gate; exits non-zero only in
  `block` mode on a failure.
- **Reusable workflow** — `.github/workflows/sentinel-gate-reusable.yml`: `workflow_call` job that
  installs pinned Syft + Grype, generates the SBOM, runs the engine, posts/updates a single PR
  comment (idempotent), and writes a job summary.
- **Caller workflow** — `.github/workflows/sentinel-gate.yml`: the per-repo caller that invokes the
  reusable workflow with `mode` and `critical-threshold` inputs.
- **Config** — `programs/secure-build/sentinel-gate.yaml`: mode + threshold + tool pins. Thresholds
  live here, not in the engine.

### Modes — warn vs block

The gate has two modes, set per caller:

- **`warn`** — the gate posts its verdict (PR comment + job summary) but exits 0, so the team
  watches the signal on real PRs without blocking anyone. The merge-but-dormant starting point.
- **`block`** — a FAIL or ERROR exits non-zero and the check turns red. To **enforce**:
  1. Flip `mode: warn` → `mode: block` in the caller workflow (one line).
  2. Make the **Secure Build Gate (Sentinel)** check **required** in branch protection.

No engine change is needed for either step.

### Adopting on another repo

Add a ~3-line caller to the target repo:

```yaml
jobs:
  secure-build-gate:
    uses: <your-org>/<your-security-repo>/.github/workflows/sentinel-gate-reusable.yml@main
    with: { mode: warn, critical-threshold: 0 }
    secrets: inherit
```

---

## Routing (findings hand-offs)

Sentinel is **emit-only**: it emits a *blocked-build* finding (Domain 8) and routes remediation
*out*; nothing routes *to* it (a build gate is a source, not a sink — a hop to it is an off-matrix
poisoning signal). Slices of [findings/HANDOFF_PROTOCOL.md](../../../findings/HANDOFF_PROTOCOL.md):

| Blocked-build cause | `suggested_next` |
|---|---|
| CRITICAL CVE in a dependency (triage real vs FP, fix vs suppress) | `[tank]` |
| Exploitability contested before gating | `[neo]` (row 15) |
| A failing control you attest to | `[keymaker]` (row 13) |
| Broader dep/SDLC posture | name `cypher` in the body (cypher is emit-only — don't route to it) |

Engineering-side follow-through is a pointer, not a route: once Tank calls a blocked dep real,
[`/roland`](../../../.claude/commands/roland.md) runs the upgrade; pre-merge,
[`/dozer`](../../../.claude/commands/dozer.md) reviews new deps before the gate sees them. See
[Engineering SDLC agents](../../engineering-sdlc-agents.md).

---

## Relationship to the rest of the roster

- **SBOM create / SBOM validate** generate and structurally validate the SBOM artifact; Sentinel
  *gates* a build on that same artifact (it shells out to `sbom_validate.py` for the completeness
  check — no re-implementation).
- **Tank** triages the CRITICAL CVEs a blocked build surfaces (fix vs suppress).
- **Cypher** owns the broader appsec/dep posture; Sentinel is the per-build enforcement point.
- **Your container-image vuln-scan workflow** is the complementary *image* gate (Trivy/Scout/Wiz/
  Aikido on a built container); Sentinel is the *source/SBOM* gate.

---

## Caveat — capability, not usage

Sentinel measures whether the gate *can* block a build, and (once flipped to `block`) that it
*does*. A green gate in `warn` mode means the verdict is visible, not enforced. Always state the mode
when reporting a verdict so a warn-mode PASS is never mistaken for an enforced gate.
