# Tracer — Requirements-to-Test Traceability Agent Runbook

**Character**: Tracer — one who follows a thread to its source
**Domain**: CISSP Domain 6 — Security Assessment & Testing (OWASP SAMM Verification / Requirements-driven Testing)
**Skill**: [`/tracer`](../../../.claude/commands/tracer.md)
**Status**: Wired — deterministic extractor + interactive skill; emit-only in the findings roster

---

## What it does

Tracer follows a single thread from a **requirement** to the **test that proves it**. The roster
authors requirements (your spec/requirements document) and reviews changes (The Architect,
`pr-review`, `sdd-review`) — but no agent proves each security requirement maps to a passing test or
control. Tracer closes that loop: it reads a spec, extracts its security requirements, and produces a
**coverage matrix** that says, per requirement, exactly which test or control verifies it — or that
nothing does.

It runs a deterministic, model-free extractor over one spec:

1. **Parse** the spec's FR-NNN functional requirements (+ MUST/SHOULD/MAY level), SC-N success
   criteria, and `AISVS C<n>` chapter references (labelled from the AISVS registry).
2. **Scan** the verification surface (`tests/` + `.github/workflows/`) for references back to each
   requirement.
3. **Classify** each requirement `covered` (explicit, scoped citation) · `inferred` (strong keyword
   match) · `unmapped` (no link), and emit a markdown + JSON matrix.

> **No false-green.** A requirement is `covered` ONLY on an explicit citation (a test/control naming
> its id + the spec's scope). A keyword match is `inferred` and never counts toward coverage; an
> untested requirement is `unmapped`, never silently passed. The headline coverage % counts explicit
> citations only.

> **Spec-local ids are scoped.** Every spec has an `FR-001`; a bare `FR-001` token counts as covering
> *this* spec only when the file also references the spec's ticket id / stem. AISVS chapters are global
> ids, matched unscoped.

---

## How to invoke

```text
/tracer                      # list specs/, pick one to trace
/tracer specs/sec-1234-*.md  # trace a specific spec
```

Or run the extractor directly:

```bash
python3 .github/scripts/tracer_trace.py --spec specs/sec-1234-*.md \
  --md .work/tracer/<stem>-matrix.md --json .work/tracer/<stem>-matrix.json
```

Tracer can dogfood itself: running the extractor against its own spec shows its unit-tested
requirements as `covered` (cited in `tests/test_tracer_trace.py`) and its skill-layer requirements as
`unmapped` — an honest, live example of the matrix.

---

## Components

- **Extractor** — [`.github/scripts/tracer_trace.py`](../../../.github/scripts/tracer_trace.py): the
  pure, deterministic parse-and-match core (no model call). CLI emits markdown (`--md`) + JSON
  (`--json`); exits non-zero only when the spec can't be read.
- **Tests** — [`tests/test_tracer_trace.py`](../../../tests/test_tracer_trace.py): prove the parser,
  the explicit-vs-inferred matcher, the spec-scope guard, and the no-false-green summary, with a
  synthetic file map (no API, no disk). `python3 tests/test_tracer_trace.py`.
- **AISVS chapter registry** —
  [`programs/verification/aisvs-chapters.yaml`](../../../programs/verification/aisvs-chapters.yaml):
  the OWASP AISVS chapter label catalog. Config, not code — Tracer degrades to generic chapter text if
  it's absent.

### CI follow-up (designed-for, not built)

A future `tracer-trace.yml` will run the extractor on every changed spec in a PR and post the matrix
as a comment, mirroring `sentinel-gate.yml` / `samm-audit.yml`. The extractor's `--json` output and
stable exit-code contract are shaped so that job is a thin wrapper, not a rewrite.

---

## The coverage convention

Tracer establishes a lightweight, durable convention that keeps the matrix green by construction:

> **Cite the requirement id in the test/control that proves it** — e.g. `# covers FR-003` in a test
> docstring, or `SEC-1234 FR-002` in a workflow comment. Include the spec's ticket id so the citation
> is scoped to the right spec.

A cited requirement is `covered`. An uncited-but-plausible test is `inferred` (add the citation to
flip it). An untested requirement is `unmapped` — the gap to close.

---

## Routing (findings hand-offs)

Tracer is **emit-only**: it emits a *coverage-gap* finding (Domain 6) and routes remediation *out*;
nothing routes *to* it (a traceability check is a source, not a sink — a hop to it is an off-matrix
poisoning signal). Slices of [findings/HANDOFF_PROTOCOL.md](../../../findings/HANDOFF_PROTOCOL.md):

| Coverage gap | `suggested_next` |
|---|---|
| Untested requirement needs a test/control written (concrete change to review) | `[architect]` (row 16) |
| Requirement's verification/exploitability is contested | `[neo]` (row 15) |
| A control we attest to has no verifying test (compliance) | `[keymaker]` (row 13, +`seraph` for $-figure) |
| Genuinely cross-domain / unclassifiable gap | `[security-steve]` (row 19) |

The usual hand-off is `[architect]` — a missing test is a change to review. Where the next step is
writing a test in a non-roster team's suite, name that team in the finding's *Recommended action*.

---

## Relationship to the rest of the roster

- **Your spec/requirements document** authors the FR-NNN requirements Tracer reads — Tracer is the
  verification counterpart to that authoring.
- **The Architect / pr-review / sdd-review** review the *change* that adds a missing test (Tracer's
  usual `[architect]` hand-off); they carry design findings forward, Tracer carries the
  requirement→test mapping.
- **Sentinel** gates the *build* on SBOM/CVE thresholds; Tracer gates *traceability* of requirements
  to tests. Different verification axes — Sentinel proves the build is clean, Tracer proves each
  requirement is tested.
- **samm-audit** scores the SAMM practice Tracer closes (Verification / Requirements-driven Testing).

---

## Caveat — capability, not usage

Tracer measures whether a requirement *can be traced* to a test/control — not that the test *passed
this run*. A `covered` row means a control cites the requirement; running that control is the test
suite's / Sentinel's job. State this when reporting so `covered` is never read as "verified green
right now". The matrix is a static traceability artifact — the same "wired ≠ active" honesty the
roster's status column applies.
