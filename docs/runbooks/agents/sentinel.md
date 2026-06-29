# Sentinel — Secure Build Gate Agent Runbook

**Character**: Sentinel from *The Matrix* — the machines that hunt in the real world
**Domain**: CISSP Domain 8 — Software Development Security (OWASP SAMM Implementation / Secure Build)
**Skill**: [`/sentinel`](../../../.claude/commands/sentinel.md)
**Status**: Ships in **warn mode** first (visible verdict, not yet blocking); emit-only in the findings roster

---

## What it does

Sentinel is the first roster agent that **blocks an insecure build** rather than documenting one.
Every other build-security agent (`sbom-create`, `sbom-validate`, `aibom-create`, Cypher) *surfaces*
artifacts; `pr-review`/Architect are human-gated. Sentinel **gates**: a non-zero exit + a red PR
status check when a build can't be proven clean.

It runs three fail-closed checks over a repo's CycloneDX SBOM:

1. **SBOM present** — the file exists, parses as CycloneDX, has ≥1 component.
2. **SBOM complete** — delegates to your existing SBOM-validation script (path-leak / secret / shape).
3. **CRITICAL ≤ threshold** — Grype over the SBOM, FAIL if CRITICAL CVEs exceed the configured count.

It reuses the proven **Syft → Grype** pipeline (Syft builds the SBOM; Grype reads CycloneDX natively)
— the same path the SBOM-create tooling (Syft) and an SBOM-scanning dashboard (Grype) run. No new
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

- **Engine** — your secure-build gate script (`sentinel_gate.py`): the three-check gate; exits
  non-zero only in `block` mode on a failure.
- **Reusable workflow** — a `workflow_call` job that installs pinned Syft + Grype, generates the
  SBOM, runs the engine, posts/updates a single PR comment (idempotent), and writes a job summary.
- **Pilot caller** — runs on your repo's PRs in **warn mode**, `critical-threshold: 0`.
- **Config** — your secure-build gate config: mode + threshold + tool pins. Thresholds live here,
  not in the engine.

### Rollout — warn → block

Ship the gate in `warn` mode first (the merge-but-dormant discipline): the gate posts its verdict but
exits 0, so the team watches the signal on real PRs without blocking anyone. To **enforce**:

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
| A failing control we attest to | `[keymaker]` (row 13) |
| Broader dep/SDLC posture | name `cypher` in the body (cypher is emit-only — don't route to it) |

---

## Relationship to the rest of the roster

- **sbom-create / sbom-validate** generate and structurally validate the SBOM artifact; Sentinel
  *gates* a build on that same artifact (it shells out to your SBOM-validation script for the
  completeness check — no re-implementation).
- **Tank** triages the CRITICAL CVEs a blocked build surfaces (fix vs suppress).
- **Cypher** owns the broader appsec/dep posture; Sentinel is the per-build enforcement point.
- **The container-image vuln-scan workflow** is the complementary *image* gate (Trivy/Scout/Wiz/
  Aikido on a built container); Sentinel is the *source/SBOM* gate.

---

## Caveat — capability, not usage

Sentinel measures whether the gate *can* block a build, and (once flipped to `block`) that it
*does*. A green gate in `warn` mode means the verdict is visible, not enforced. Always state the mode
when reporting a verdict so a warn-mode PASS is never mistaken for an enforced gate.
