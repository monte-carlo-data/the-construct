#!/usr/bin/env python3
"""
Loop 4 — Hill-climbing analysis over the findings/ ledger.

The Matrix teamwork layer implements three of the four loops from LangChain's
"Art of Loop Engineering": agent core, verification (Zero Trust between hops), and
event-driven triggers (security-steve orchestrate / a scheduled digest / sensor
emits). This script is the fourth — **hill climbing**: it reads the shared
findings ledger + the handoff matrix, spots routing/allow-set drift and dead-end
patterns, and emits **proposals** to improve the harness config.

Hard rule (non-negotiable): this NEVER edits the matrix or the allow-set. Its
output is (a) a human-reviewed proposal doc and (b) a finding in the ledger. A
human opens the PR against HANDOFF_PROTOCOL.md. This loop codifies routine
oversight; it does not auto-mutate routing.

Five analyses (some degrade gracefully on a thin ledger / no FP store):
  A. Allow-set drift — recompute the matrix-target allow-set from the live
     matrix rows and diff it against the hardcoded block in HANDOFF_PROTOCOL §
     Zero Trust Rule 2. Closes the doc's manual "regenerate this list" step.
     (Complements findings_validate.check_contract, which FAILS CI on drift;
     hill_climb PROPOSES the corrected block text. Fail vs. fix, not duplicate.)
  B. Empirical routing critique — per finding-type, tally outcomes across the
     ledger: rows whose findings consistently dead-end (empty suggested_next +
     still open), route to an agent that no-ops, or get re-routed by hand. Below
     MIN_SIGNAL findings for a type, report "insufficient signal" — never
     fabricate a critique.
  C. Off-matrix / poisoned-finding rollup — aggregate off-matrix / off-roster
     suggested_next slugs (the Zero-Trust Rule 4 provenance signal) grouped by
     emitting agent, turning the per-run flag into a per-source pattern.
  D. Severity x type evidence — surface where severity plausibly shifted the
     effective route, as evidence to inform the deferred severity x type grid.
     Evidence only; proposes no grid.
  E. Recurring-FP rollup — read an FP suppression store (the Analyst's
     fp_signatures) and roll up active suppressions by detection. A high
     hit_count means the upstream SIEM detection keeps re-firing on a benign
     pattern, so the durable fix is detection TUNING (owned by the human team
     that maintains your detections-as-code repo), not an ever-growing
     allow-set. PROPOSES tuning; never writes to the SIEM or the allow-set.
     Degrades to "no FP data" without a store.

Design: read-only ledger consumer, deterministic Python (no model produces a
count), fail-soft on a bad file, and a --dry-run path that computes + prints
but writes nothing. Doc parsing is reused from findings_validate.py so the
roster / allow-set / matrix are never hardcoded.

Run:
    python .github/scripts/hill_climb.py --dry-run        # print analysis, write nothing
    python .github/scripts/hill_climb.py                  # write proposal doc + finding IF there's a proposal
    python .github/scripts/hill_climb.py --min-signal 5   # raise the empirical-critique threshold
Exit 0 = ran clean; 1 = a hard error (docs unreadable). A thin ledger or a
clean matrix is not an error — it just means no proposal.

Configuration (environment, all optional):
  FINDINGS_REPO_URL        — base URL of the repo that hosts findings/ and the proposal
                             doc, used in the emitted finding's evidence links
                             (default: https://github.com/your-org/your-security-repo).
  ANALYST_FP_TABLE         — name of the Analyst's FP suppression table. Unset => analysis
                             E reports "no FP data" and proposes nothing.
  ANALYST_FP_STORE_MODULE  — path to the Python module that exposes
                             `DynamoDbFpStore(table, region).scan_active_fps()` (the
                             Analyst's fp_store). Required with ANALYST_FP_TABLE.
  AWS_REGION               — region for the FP store client.
Dependencies: Python 3.11+ and PyYAML (`pip install pyyaml`), via findings_validate.py.
"""

import argparse
import hashlib
import importlib.util
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml to run the hill-climb analyzer")

REPO_ROOT = Path(__file__).resolve().parents[2]
FINDINGS_DIR = REPO_ROOT / "findings"
SCHEMA_MD = FINDINGS_DIR / "SCHEMA.md"
PROTOCOL_MD = FINDINGS_DIR / "HANDOFF_PROTOCOL.md"
PROPOSAL_DIR = REPO_ROOT / "review-routing" / "hill-climb"

# Base URL of the repo hosting findings/ + the proposal doc (evidence links in the finding).
FINDINGS_REPO_URL = os.environ.get(
    "FINDINGS_REPO_URL", "https://github.com/your-org/your-security-repo"
).rstrip("/")

# The FP suppression store (fp_signatures) is the recurring-FP data source. hill_climb reads it
# read-only via the same fp_store module the Analyst's consumer/webhook use (single-sourced
# matching). Point ANALYST_FP_STORE_MODULE at that module; unset => analysis E degrades.
FP_STORE_PY = Path(os.environ["ANALYST_FP_STORE_MODULE"]) if os.environ.get("ANALYST_FP_STORE_MODULE") else None

# A detection (or single signature) whose active suppressions have been HIT at least this many times is
# a recurring FP worth a durable-fix proposal. Overridable via --min-fp-hits.
MIN_FP_HITS_DEFAULT = 10

# Doc files + examples/ are not live findings — same exclusion the digest,
# validator, and orchestrator use.
DOC_FILES = {"README.md", "SCHEMA.md", "HANDOFF_PROTOCOL.md"}

# A finding-type needs at least this many findings before its routing outcome is
# a signal rather than noise. Overridable via --min-signal.
MIN_SIGNAL_DEFAULT = 3

# Emitter identity for the proposal finding. security-steve owns the matrix /
# allow-set machinery and is a valid roster + allow-set slug, so the finding
# validates clean and routes nowhere (self-owned proposal).
EMITTER = "security-steve"
PROPOSAL_DOMAIN = "1 — Security & Risk Management"


# ---------------------------------------------------------------------------
# Reuse the doc parsers from findings_validate.py (never hardcode roster/allow-set).
# ---------------------------------------------------------------------------

def _load_validator():
    """Import findings_validate.py as a module so we reuse its doc parsers."""
    spec = importlib.util.spec_from_file_location(
        "findings_validate", Path(__file__).with_name("findings_validate.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fv = _load_validator()
parse_roster = _fv.parse_roster
parse_allow_set = _fv.parse_allow_set
parse_matrix_union = _fv.parse_matrix_union
parse_domains = _fv.parse_domains
load_frontmatter = _fv.load_frontmatter


# ---------------------------------------------------------------------------
# Matrix-row parsing (per-row, not just the union — analyses B/D need the row).
# ---------------------------------------------------------------------------

def parse_matrix_rows(protocol_text: str) -> list[dict]:
    """Parse the handoff matrix into per-row dicts.

    Row shape in the doc:
        | # | **Finding-type** | `[slug, slug]` | Rationale | emitter, emitter |

    Returns a list of {row, finding_type, targets(set), emitters(set)}. The
    row label ("7b", "20") is kept as a string so B/D can reference it.
    """
    import re

    matrix = (
        protocol_text.split("## The handoff matrix")[1]
        .split("## `suggested_next` population logic")[0]
    )
    rows = []
    for line in matrix.splitlines():
        line = line.strip()
        # A data row starts with "| <label> |" where label is like 1, 7b, 20b.
        m = re.match(r"^\|\s*([0-9]+[a-z]?)\s*\|(.*)\|\s*$", line)
        if not m:
            continue
        label = m.group(1)
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) < 4:
            continue
        finding_type = cells[0].strip("* ").strip()
        # targets: the `[...]` code-span in the suggested_next cell (plus any
        # extra backticked slug like `add seraph` — union all slugs in the cell).
        sn_cell = cells[1]
        targets = set()
        for span in re.findall(r"`\[([^\]]*)\]`", sn_cell):
            targets.update(re.findall(r"[a-z0-9-]+", span))
        # a bare "add `seraph`" style extra target mentioned in the same cell
        for extra in re.findall(r"add\s+`([a-z0-9-]+)`", sn_cell):
            targets.add(extra)
        emitters = set(re.findall(r"[a-z0-9-]+", cells[3])) if len(cells) > 3 else set()
        rows.append({
            "row": label,
            "finding_type": finding_type,
            "targets": targets,
            "emitters": emitters,
        })
    return rows


# ---------------------------------------------------------------------------
# Ledger loading (fail-soft).
# ---------------------------------------------------------------------------

def load_ledger() -> tuple[list[dict], list[str]]:
    """Parse every live finding. Returns (findings, problems).

    Each finding dict is its frontmatter plus "_body" and "_path". A file that
    can't be parsed is reported in `problems` and skipped — never fatal.
    """
    findings: list[dict] = []
    problems: list[str] = []
    if not FINDINGS_DIR.is_dir():
        problems.append(f"findings/ not found at {FINDINGS_DIR}")
        return findings, problems

    for path in sorted(FINDINGS_DIR.glob("*.md")):
        if path.name in DOC_FILES:
            continue
        try:
            text = path.read_text()
        except Exception as e:  # noqa: BLE001
            problems.append(f"{path.name}: unreadable ({e})")
            continue
        if not text.startswith("---"):
            problems.append(f"{path.name}: no frontmatter")
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            problems.append(f"{path.name}: malformed frontmatter")
            continue
        try:
            data = yaml.safe_load(parts[1])
        except yaml.YAMLError as e:
            problems.append(f"{path.name}: YAML parse error ({e})")
            continue
        if not isinstance(data, dict):
            problems.append(f"{path.name}: frontmatter is not a mapping")
            continue
        data["_body"] = parts[2].strip()
        data["_path"] = path.name
        findings.append(data)
    return findings, problems


def ledger_git_dates() -> dict[str, str]:
    """Best-effort first-commit date per findings/ file, from git history.

    Used by the off-matrix rollup (C) to say "across runs" instead of "this
    run". Returns {} if git is unavailable — the analysis degrades to the
    current ledger snapshot, which is still correct, just not historical.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "log", "--diff-filter=A",
             "--format=%ad", "--date=short", "--name-only", "--", "findings/"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:  # noqa: BLE001
        return {}
    if out.returncode != 0:
        return {}
    dates: dict[str, str] = {}
    current_date = None
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) == 10 and line[4] == "-" and line[7] == "-":
            current_date = line
        elif line.startswith("findings/") and line.endswith(".md"):
            name = line.split("/")[-1]
            # keep the earliest (git log is newest-first; overwrite → oldest wins)
            dates[name] = current_date
    return dates


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def classify_finding_type(finding: dict, rows: list[dict]) -> str | None:
    """Best-effort map a finding to a matrix row label via its suggested_next.

    We do NOT re-derive routing from the body (untrusted input, Zero Trust Rule 1). We
    infer which row the emitter *used* by matching the finding's actual
    suggested_next set against each row's target set. Exact-set match wins; a
    subset match is the fallback. An empty suggested_next matches the empty-route
    rows (7). Returns the row label or None if no row matches.
    """
    sn = frozenset(str(s) for s in (finding.get("suggested_next") or []))
    # exact match first
    for r in rows:
        if r["targets"] == sn and sn:
            return r["row"]
    # empty-route rows for a [] finding
    if not sn:
        for r in rows:
            if not r["targets"]:
                return r["row"]
        return None
    # subset fallback (union-of-rows case: emitter combined multiple rows)
    for r in rows:
        if r["targets"] and r["targets"] <= sn:
            return r["row"]
    return None


# ---------------------------------------------------------------------------
# Analysis A — allow-set drift
# ---------------------------------------------------------------------------

def analyze_allowset_drift(protocol_text: str, roster: set) -> dict:
    """Recompute the allow-set from the matrix rows; diff vs the documented block.

    Returns {drift(bool), documented(sorted list), derived(sorted list),
    block_only, matrix_only, off_roster, proposed_block(str)}.
    """
    documented = parse_allow_set(protocol_text)
    derived = parse_matrix_union(protocol_text)
    block_only = sorted(documented - derived)   # in the block, no row routes there
    matrix_only = sorted(derived - documented)  # a row routes there, block missing it
    off_roster = sorted(derived - roster)       # a target that isn't even a real agent
    proposed = _format_allowset_block(sorted(derived))
    return {
        "drift": documented != derived,
        "documented": sorted(documented),
        "derived": sorted(derived),
        "block_only": block_only,
        "matrix_only": matrix_only,
        "off_roster": off_roster,
        "proposed_block": proposed,
    }


def _format_allowset_block(slugs: list[str]) -> str:
    """Render the allow-set as the two-line fenced block the doc uses."""
    if not slugs:
        return "(empty)"
    mid = (len(slugs) + 1) // 2
    line1 = ", ".join(slugs[:mid]) + ","
    line2 = ", ".join(slugs[mid:]) + f"        ({len(slugs)} slugs)"
    return f"{line1}\n{line2}"


# ---------------------------------------------------------------------------
# Analysis B — empirical routing critique
# ---------------------------------------------------------------------------

def analyze_routing(findings: list[dict], rows: list[dict], min_signal: int) -> dict:
    """Per finding-type routing outcomes across the ledger.

    Dead-end: findings that ended with an empty suggested_next AND are still
    `open` (no human/agent picked them up). Below min_signal findings for a
    type, we report insufficient signal rather than a critique.
    """
    by_row = defaultdict(list)
    unclassified = []
    for f in findings:
        label = classify_finding_type(f, rows)
        if label is None:
            unclassified.append(f.get("id", f.get("_path", "?")))
        else:
            by_row[label].append(f)

    row_index = {r["row"]: r for r in rows}
    critiques = []
    insufficient = []
    for label, fs in sorted(by_row.items()):
        n = len(fs)
        row = row_index.get(label, {})
        ftype = row.get("finding_type", "?")
        if n < min_signal:
            insufficient.append({"row": label, "finding_type": ftype, "count": n})
            continue
        dead_ends = [f for f in fs
                     if not (f.get("suggested_next") or [])
                     and str(f.get("status", "")).lower() == "open"]
        if len(dead_ends) == n:
            critiques.append({
                "row": label, "finding_type": ftype, "count": n,
                "pattern": "all-dead-end",
                "detail": (f"all {n} finding(s) of this type ended with an empty "
                           f"suggested_next and are still `open` — the row may need a "
                           f"route target, or the owning team named in the body is not "
                           f"closing them"),
            })
    return {
        "min_signal": min_signal,
        "by_row_counts": {k: len(v) for k, v in sorted(by_row.items())},
        "unclassified": unclassified,
        "critiques": critiques,
        "insufficient_signal": insufficient,
    }


# ---------------------------------------------------------------------------
# Analysis C — off-matrix / poisoned-finding rollup (per source, across runs)
# ---------------------------------------------------------------------------

def analyze_offmatrix(findings: list[dict], roster: set, allow_set: set,
                      git_dates: dict) -> dict:
    """Aggregate off-matrix / off-roster suggested_next slugs by emitting agent.

    Turns the per-run Zero-Trust flag into a per-source pattern. Off-roster is a
    stronger signal than off-matrix (a slug that isn't even an agent).
    """
    per_source = defaultdict(lambda: {"off_matrix": [], "off_roster": [], "dates": set()})
    total = 0
    for f in findings:
        agent = str(f.get("agent", "unknown"))
        fid = f.get("id", f.get("_path", "?"))
        date = git_dates.get(f.get("_path", ""), None)
        for slug in (f.get("suggested_next") or []):
            slug = str(slug)
            if slug not in roster:
                per_source[agent]["off_roster"].append((fid, slug))
                if date:
                    per_source[agent]["dates"].add(date)
                total += 1
            elif slug not in allow_set:
                per_source[agent]["off_matrix"].append((fid, slug))
                if date:
                    per_source[agent]["dates"].add(date)
                total += 1
    sources = []
    for agent, d in sorted(per_source.items()):
        sources.append({
            "agent": agent,
            "off_matrix": d["off_matrix"],
            "off_roster": d["off_roster"],
            "distinct_dates": sorted(d["dates"]),
        })
    return {"total_off": total, "sources": sources}


# ---------------------------------------------------------------------------
# Analysis D — severity x type evidence
# ---------------------------------------------------------------------------

def analyze_severity_route(findings: list[dict], rows: list[dict]) -> dict:
    """Evidence for the deferred severity x type grid.

    For each finding-type (matrix row), record the distinct severities seen and
    whether the finding's actual route differed across severities. A type that
    routes differently at different severities is evidence the grid would
    formalize. Evidence only — proposes no grid.
    """
    by_type = defaultdict(lambda: defaultdict(set))  # ftype -> severity -> frozenset(route)
    for f in findings:
        label = classify_finding_type(f, rows)
        if label is None:
            continue
        sev = str(f.get("severity", "unknown")).lower()
        route = frozenset(str(s) for s in (f.get("suggested_next") or []))
        by_type[label][sev].add(route)

    evidence = []
    for label, sev_map in sorted(by_type.items()):
        # a route that varies across severities for the same type
        all_routes = set().union(*sev_map.values()) if sev_map else set()
        if len(sev_map) > 1 and len(all_routes) > 1:
            evidence.append({
                "row": label,
                "severities": {s: [sorted(r) for r in routes]
                               for s, routes in sorted(sev_map.items())},
            })
    return {"evidence": evidence}


# ---------------------------------------------------------------------------
# Analysis E — recurring-FP rollup: active suppressions by detection
# ---------------------------------------------------------------------------

def load_fp_entries() -> tuple[list[dict], str | None]:
    """Read active FP suppressions from the fp_signatures store — the recurring-FP source.

    Fail-soft: returns ([], reason) when no table is configured or the scan errors, so hill-climb
    still runs locally and in CI without production DynamoDB creds — analysis E just reports "no FP
    data" rather than failing the run. Reuses the Analyst's fp_store module so the entry shape and
    active-fp filter can never drift from how suppressions are written.
    """
    table = os.environ.get("ANALYST_FP_TABLE")
    if not table:
        return [], "ANALYST_FP_TABLE unset — no FP suppression store to analyze"
    if FP_STORE_PY is None or not FP_STORE_PY.is_file():
        return [], "ANALYST_FP_STORE_MODULE unset or not a file — cannot read the FP suppression store"
    try:
        spec = importlib.util.spec_from_file_location("fp_store", FP_STORE_PY)
        fp_store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fp_store)
        store = fp_store.DynamoDbFpStore(table=table, region=os.environ.get("AWS_REGION"))
        return store.scan_active_fps(), None
    except Exception as e:  # noqa: BLE001 — never fail the whole hill-climb on the FP read
        return [], f"FP store scan failed ({type(e).__name__}: {e})"


def analyze_recurring_fp(entries: list[dict], min_hits: int) -> dict:
    """Roll up active FP suppressions by detection to surface recurring benign patterns.

    A suppression short-circuits a known FP, but a HIGH hit_count means the upstream SIEM detection
    keeps re-firing on a benign pattern — the durable fix is detection tuning (owned by the HUMAN
    team that maintains your detections-as-code repo — not the emit-only `panther` sensor agent,
    which is never a route target), not an ever-growing allow-set. A whole detection OR any single
    signature crossing `min_hits` is the trigger. `entries` are active-fp rows from the store
    (scan_active_fps). PURE — proposes, writes nothing; the caller renders it into the shared
    proposal doc + finding.
    """
    by_detection: dict[str, dict] = defaultdict(lambda: {"total_hits": 0, "signatures": []})
    for e in entries:
        det = str(e.get("detection", "(unknown)"))
        hits = int(e.get("hit_count", 0) or 0)
        by_detection[det]["total_hits"] += hits
        by_detection[det]["signatures"].append({
            "sig_hash": str(e.get("sig_hash", "?")),
            "hit_count": hits,
            "principal": str(e.get("principal", "")),
            "source": str(e.get("source", "")),
            "resource": str(e.get("resource", "")),
            "action": str(e.get("action", "")),
        })
    recurring = []
    for det, d in by_detection.items():
        top = max((s["hit_count"] for s in d["signatures"]), default=0)
        if d["total_hits"] >= min_hits or top >= min_hits:
            recurring.append({
                "detection": det,
                "total_hits": d["total_hits"],
                "signature_count": len(d["signatures"]),
                "top_hit": top,
                "signatures": sorted(d["signatures"], key=lambda s: -s["hit_count"]),
            })
    recurring.sort(key=lambda r: (-r["total_hits"], r["detection"]))
    return {
        "min_hits": min_hits,
        "active_fp_count": len(entries),
        "detections_considered": len(by_detection),
        "recurring": recurring,
    }


# ---------------------------------------------------------------------------
# Roll the analyses into one report + decide whether to propose
# ---------------------------------------------------------------------------

def build_report(min_signal: int, min_fp_hits: int = MIN_FP_HITS_DEFAULT) -> dict:
    protocol_text = PROTOCOL_MD.read_text()
    schema_text = SCHEMA_MD.read_text()
    roster = parse_roster(schema_text)
    allow_set = parse_allow_set(protocol_text)
    rows = parse_matrix_rows(protocol_text)

    findings, problems = load_ledger()
    git_dates = ledger_git_dates()
    fp_entries, fp_note = load_fp_entries()

    report = {
        "ledger_count": len(findings),
        "problems": problems,
        "matrix_rows": len(rows),
        "A_allowset": analyze_allowset_drift(protocol_text, roster),
        "B_routing": analyze_routing(findings, rows, min_signal),
        "C_offmatrix": analyze_offmatrix(findings, roster, allow_set, git_dates),
        "D_severity": analyze_severity_route(findings, rows),
        "E_recurring_fp": analyze_recurring_fp(fp_entries, min_fp_hits),
    }
    report["E_recurring_fp"]["source_note"] = fp_note
    report["has_proposal"] = _has_proposal(report)
    return report


def _has_proposal(report: dict) -> bool:
    """A proposal is worth emitting if ANY analysis found something actionable."""
    return bool(
        report["A_allowset"]["drift"]
        or report["B_routing"]["critiques"]
        or report["C_offmatrix"]["total_off"]
        or report["D_severity"]["evidence"]
        or report["E_recurring_fp"]["recurring"]
    )


# ---------------------------------------------------------------------------
# Rendering — the human-readable analysis (console + proposal doc share this)
# ---------------------------------------------------------------------------

def render_analysis(report: dict) -> str:
    a = report["A_allowset"]
    b = report["B_routing"]
    c = report["C_offmatrix"]
    d = report["D_severity"]
    L = []

    L.append("## A. Allow-set drift (matrix-target allow-set vs the documented block)")
    if a["drift"]:
        L.append("**DRIFT DETECTED.** The documented allow-set block in HANDOFF_PROTOCOL "
                 "§ Zero Trust Rule 2 no longer equals the union of the matrix rows.")
        if a["matrix_only"]:
            L.append(f"- Rows route to these slug(s) but the block omits them: "
                     f"`{', '.join(a['matrix_only'])}`")
        if a["block_only"]:
            L.append(f"- The block lists these but no row routes there: "
                     f"`{', '.join(a['block_only'])}`")
        if a["off_roster"]:
            L.append(f"- ⚠️ A row routes to a NON-roster slug (real bug, not just drift): "
                     f"`{', '.join(a['off_roster'])}`")
        L.append("\n**Proposed replacement for the fenced allow-set block "
                 "(regenerate per 'derived, not hand-maintained'):**\n")
        L.append("```text")
        L.append(a["proposed_block"])
        L.append("```")
        L.append("\n_This closes the manual 'regenerate this list' step. "
                 "`findings_validate.py` already FAILS CI on this drift; this proposal "
                 "supplies the corrected block text for the PR._")
    else:
        L.append(f"No drift. The documented block equals the union of the matrix rows "
                 f"({len(a['derived'])} route targets). Nothing to propose.")
    L.append("")

    L.append("## B. Empirical routing critique (per finding-type outcomes across the ledger)")
    L.append(f"Signal threshold: ≥{b['min_signal']} findings per type.")
    if b["by_row_counts"]:
        L.append(f"Findings classified by row: {b['by_row_counts']}")
    if b["unclassified"]:
        L.append(f"Unclassifiable against the matrix (suggested_next matched no row): "
                 f"{b['unclassified']}")
    if b["critiques"]:
        for cr in b["critiques"]:
            L.append(f"- **Row {cr['row']}** ({cr['finding_type']}), {cr['count']} findings — "
                     f"{cr['pattern']}: {cr['detail']}")
    else:
        L.append("No routing critique above the signal threshold.")
    if b["insufficient_signal"]:
        thin = ", ".join(f"row {x['row']} ({x['count']})" for x in b["insufficient_signal"])
        L.append(f"_Insufficient signal (below threshold, no critique made): {thin}. "
                 f"These activate as the ledger grows._")
    L.append("")

    L.append("## C. Off-matrix / poisoned-finding rollup (per emitting source, across runs)")
    if c["total_off"]:
        L.append(f"**{c['total_off']} off-matrix/off-roster hop(s)** aggregated by source "
                 f"(Zero Trust Rule 4 — provenance is attributable):")
        for s in c["sources"]:
            when = f" on {', '.join(s['distinct_dates'])}" if s["distinct_dates"] else ""
            if s["off_roster"]:
                L.append(f"- `{s['agent']}` → OFF-ROSTER (not even an agent){when}: "
                         + ", ".join(f"{fid}→`{slug}`" for fid, slug in s["off_roster"]))
            if s["off_matrix"]:
                L.append(f"- `{s['agent']}` → off-matrix (no row routes there){when}: "
                         + ", ".join(f"{fid}→`{slug}`" for fid, slug in s["off_matrix"]))
        L.append("_A source with a recurring pattern here is a poisoned-finding signal "
                 "worth a human look, not just a per-run flag._")
    else:
        L.append("No off-matrix or off-roster hops in the live ledger. Clean.")
    L.append("")

    L.append("## D. Severity × type evidence (informs the deferred severity × type grid)")
    if d["evidence"]:
        L.append("These finding-types routed **differently at different severities** — evidence "
                 "the deferred severity × type grid would formalize (HANDOFF_PROTOCOL Open Questions):")
        for e in d["evidence"]:
            L.append(f"- **Row {e['row']}**: {e['severities']}")
        L.append("_Evidence only — this analysis proposes no grid; it hands the human the data._")
    else:
        L.append("No finding-type shows a severity-dependent route in the ledger yet "
                 "(need ≥2 severities of the same type with different routes). "
                 "Insufficient signal for the grid.")
    L.append("")

    fp = report["E_recurring_fp"]
    L.append("## E. Recurring-FP rollup (active suppressions by detection → durable-fix proposals)")
    if fp.get("source_note"):
        L.append(f"_{fp['source_note']}._")
    if fp["recurring"]:
        L.append(f"Signal threshold: ≥{fp['min_hits']} suppression hits (per detection or single "
                 f"signature). {fp['active_fp_count']} active suppression(s) across "
                 f"{fp['detections_considered']} detection(s).")
        for r in fp["recurring"]:
            L.append(f"- **{r['detection']}** — {r['total_hits']} hit(s) across "
                     f"{r['signature_count']} signature(s) (top {r['top_hit']}). Durable fix: "
                     f"**upstream Panther tuning** (owner: your detections-as-code team) — the "
                     f"suppression is masking a benign pattern the detection keeps re-firing on. "
                     f"Top signatures:")
            for s in r["signatures"][:5]:
                scope = ", ".join(f"{k}=`{s[k]}`" for k in ("principal", "source", "resource", "action")
                                  if s.get(k))
                L.append(f"    - `{s['sig_hash']}` ({s['hit_count']} hit(s))"
                         + (f" — {scope}" if scope else ""))
        L.append("_Proposal only — a human tunes the Panther detection (durable) or keeps the "
                 "suppression (band-aid). This loop makes ZERO writes to Panther or the allow-set._")
    elif not fp.get("source_note"):
        L.append(f"No detection crossed the recurring threshold (≥{fp['min_hits']} hits). "
                 f"{fp['active_fp_count']} active suppression(s); nothing to propose.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Emit path — proposal doc + finding (only when there's a proposal)
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_proposal_doc(report: dict, date: str) -> str:
    return (
        f"# Handoff-matrix hill-climb proposal — {date}\n\n"
        f"**Generated by:** `/hill-climb` (Loop 4). "
        f"**Emitter:** `{EMITTER}`.\n\n"
        f"> **This is a proposal, not a change.** A human reviews it and opens the PR against "
        f"[`findings/HANDOFF_PROTOCOL.md`](../../findings/HANDOFF_PROTOCOL.md). This loop never "
        f"auto-edits the matrix or the allow-set (hard rule).\n\n"
        f"Ledger analyzed: {report['ledger_count']} live finding(s); "
        f"{report['matrix_rows']} matrix rows.\n\n"
        f"---\n\n"
        f"{render_analysis(report)}\n"
    )


def render_finding(report: dict, date: str) -> tuple[str, str]:
    """Return (finding_id, finding_markdown). Emitted only when has_proposal."""
    a = report["A_allowset"]
    recurring_fp = report["E_recurring_fp"]["recurring"]
    severity = "low" if (a["drift"] or recurring_fp) else "informational"
    # deterministic-ish short hash from the salient facts (stable within a day)
    seed = (f"{date}|drift={a['drift']}|matrix_only={a['matrix_only']}|"
            f"crit={len(report['B_routing']['critiques'])}|"
            f"off={report['C_offmatrix']['total_off']}|"
            f"sevD={len(report['D_severity']['evidence'])}|"
            f"fp={[r['detection'] for r in recurring_fp]}")
    short = hashlib.sha1(seed.encode()).hexdigest()[:6]
    fid = f"{date}-{EMITTER}-matrix-hill-climb-{short}"

    headline_bits = []
    if a["drift"]:
        headline_bits.append("allow-set drift")
    if report["B_routing"]["critiques"]:
        headline_bits.append(f"{len(report['B_routing']['critiques'])} routing critique(s)")
    if report["C_offmatrix"]["total_off"]:
        headline_bits.append(f"{report['C_offmatrix']['total_off']} off-matrix hop(s)")
    if report["D_severity"]["evidence"]:
        headline_bits.append(f"{len(report['D_severity']['evidence'])} severity×type signal(s)")
    if recurring_fp:
        headline_bits.append(f"{len(recurring_fp)} recurring-FP tuning proposal(s)")
    headline = "; ".join(headline_bits) or "routine analysis"

    proposal_rel = f"review-routing/hill-climb/{date}-matrix-proposal.md"
    fm = {
        "schema_version": 1,
        "id": fid,
        "agent": EMITTER,
        "timestamp": _now_iso(),
        "severity": severity,
        "domain": PROPOSAL_DOMAIN,
        "subject": "handoff-matrix:hill-climb-proposal",
        "owner": "security-team",
        "status": "open",
        "evidence": [
            {"system": "github",
             "url": f"{FINDINGS_REPO_URL}/blob/main/{proposal_rel}",
             "note": "Hill-climb proposal doc — the diff-ready matrix/allow-set proposals"},
            {"system": "github",
             "url": f"{FINDINGS_REPO_URL}/blob/main/findings/HANDOFF_PROTOCOL.md",
             "note": "The handoff matrix + allow-set this proposal targets"},
        ],
        "suggested_next": [],
    }
    # hand-serialize frontmatter so the timestamp stays a quoted string (SCHEMA rule).
    fm_yaml = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False, allow_unicode=True)

    body = (
        f"## What\n\n"
        f"Loop-4 hill-climb analysis over the findings/ ledger surfaced: **{headline}**. "
        f"The diff-ready proposals live in the proposal doc (evidence link); this finding is the "
        f"ledger anchor so the proposal itself flows through the digest / orchestrate machinery.\n\n"
        f"## Why it matters\n\n"
        f"This closes Loop 4 of the teamwork layer (LangChain 'Art of Loop Engineering'): production "
        f"traces (the ledger) feed an analysis agent that proposes harness-config improvements. It "
        f"codifies the manual 'regenerate the allow-set' step and surfaces empirical routing gaps — "
        f"without ever auto-mutating the matrix (hard rule; the human owns the PR).\n\n"
        f"## Recommended action\n\n"
        f"**security-team (self):** review the proposal doc; open a PR against `HANDOFF_PROTOCOL.md` "
        f"for any change worth making. `suggested_next: []` — this is a self-owned proposal, not an "
        f"agent handoff. If the allow-set drifted, `findings_validate.py` is already failing CI; the "
        f"proposal doc has the corrected block.\n"
    )
    return fid, f"---\n{fm_yaml}---\n\n{body}"


def emit(report: dict, date: str) -> list[Path]:
    """Write the proposal doc + finding. Returns the paths written."""
    written = []
    PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)
    proposal_path = PROPOSAL_DIR / f"{date}-matrix-proposal.md"
    proposal_path.write_text(render_proposal_doc(report, date))
    written.append(proposal_path)

    fid, finding_md = render_finding(report, date)
    finding_path = FINDINGS_DIR / f"{fid}.md"
    finding_path.write_text(finding_md)
    written.append(finding_path)
    return written


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Loop 4 hill-climbing analysis over the findings/ ledger.")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and print the analysis but write nothing")
    ap.add_argument("--min-signal", type=int, default=MIN_SIGNAL_DEFAULT,
                    help=f"min findings per type before the routing critique fires "
                         f"(default {MIN_SIGNAL_DEFAULT})")
    ap.add_argument("--min-fp-hits", type=int, default=MIN_FP_HITS_DEFAULT,
                    help=f"min suppression hits (per detection or single signature) before a "
                         f"recurring-FP tuning proposal fires (default {MIN_FP_HITS_DEFAULT})")
    args = ap.parse_args()

    print(f"hill-climb — analyzing the findings/ ledger (min-signal={args.min_signal}, "
          f"min-fp-hits={args.min_fp_hits})")
    report = build_report(args.min_signal, args.min_fp_hits)
    for p in report["problems"]:
        print(f"  ⚠️ {p}", file=sys.stderr)
    print(f"  {report['ledger_count']} live finding(s); {report['matrix_rows']} matrix rows; "
          f"proposal={'yes' if report['has_proposal'] else 'no'}")

    print("\n--- analysis ---\n")
    print(render_analysis(report))
    print("\n----------------\n")

    if not report["has_proposal"]:
        print("No proposal — the matrix/allow-set are consistent and no pattern crossed a "
              "threshold. Nothing written (empty-day skip).")
        return

    if args.dry_run:
        print("DRY RUN — proposal detected but writing nothing. Re-run without --dry-run "
              "(or use /hill-climb) to write the proposal doc + finding.")
        return

    date = _today()
    written = emit(report, date)
    print("Wrote:")
    for p in written:
        print(f"  {p.relative_to(REPO_ROOT)}")
    print("\nNext: a human reviews the proposal doc and opens a PR against "
          "findings/HANDOFF_PROTOCOL.md. This loop never edits the matrix itself.")


if __name__ == "__main__":
    main()
