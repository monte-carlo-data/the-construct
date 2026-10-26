#!/usr/bin/env python3
"""Tracer — requirements-to-test traceability extractor.

This is the scheduled/triggered-ready implementation of the `/tracer` skill
(`.claude/commands/tracer.md`). The skill markdown is the SPEC; this script is the
deterministic, provable core — the "skill = spec, Python = closed-loop executable"
split the other scripts in this directory follow.

What it does (close the SAMM Verification / Requirements-driven Testing loop):

  1. PARSE one requirements spec: extract its security requirements
     (FR-NNN functional requirements, with the MUST/SHOULD/MAY level), its
     SC-N success criteria, and any AISVS chapter references.
  2. SCAN the verification surface — `tests/` and `.github/workflows/` — for
     references back to each requirement. An EXPLICIT citation (the literal
     `FR-001` / `SC-1` / `AISVS C3` token in a test docstring, name, or comment)
     is authoritative `covered`. A keyword/name match is `inferred` (a weaker,
     clearly-flagged signal). Anything with no link is honestly `unmapped`.
  3. BUILD a coverage matrix (requirement -> linked test/control -> status) and
     a summary. Unmapped requirements are the gap the loop must close.

DETERMINISM IS THE WHOLE POINT. There is no model call here: parsing and matching
are pure, auditable Python so the same spec + same tree yields the same matrix
every run (move judgment into testable code, not a sampling knob). The `/tracer`
skill layer is where a human reviews `inferred`/`unmapped` rows and decides what
becomes a tracking ticket.

NO FALSE-GREEN. A requirement is only `covered` on an explicit reference; an
`inferred` match never counts as covered in the summary's coverage figure, and a
requirement Tracer cannot link is reported `unmapped`, never silently passed.

Usage:
  tracer_trace.py --spec specs/sec-1234-....md [--json out.json] [--md matrix.md]
  tracer_trace.py --spec <path> --format {md,json}     # to stdout

Configuration (all optional):
  programs/verification/aisvs-chapters.yaml — AISVS chapter-title registry (labels only;
  absent file => generic labels). Override the location with TRACER_AISVS_REGISTRY.
  Stdlib only — no third-party imports.

Exit code: 0 always when the spec parsed (a matrix with unmapped rows is a
successful *report*, not a tool failure); 2 if the spec could not be read/parsed.
The skill, not the extractor, decides whether unmapped requirements warrant a
ticket — mirroring how a warn-mode gate reports without failing the build.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# AISVS chapter label registry (config, not code) — maps a parsed `AISVS-C<n>`
# id to its OWASP chapter title for the matrix. Optional: absent/unreadable => the
# generic fallback text is used. TRACER_AISVS_REGISTRY overrides the location.
AISVS_REGISTRY_PATH = Path(
    os.environ.get("TRACER_AISVS_REGISTRY")
    or REPO_ROOT / "programs" / "verification" / "aisvs-chapters.yaml"
)

# Where the VERIFICATION evidence lives — the surface a requirement is "tested"
# against. Tests are the primary control surface; CI workflows are controls too
# (a gate, a scan, a scheduled audit that enforces something). We deliberately do
# NOT scan `.github/scripts/` or source: a requirement being *implemented* in code
# is not the same as being *verified* by a test/control, and treating impl files
# as coverage is exactly the false-green Tracer exists to prevent. The skill can
# pass `--scan-dir` to widen the surface for a spec whose controls live elsewhere.
DEFAULT_SCAN_DIRS = ("tests", ".github/workflows")

# File extensions worth scanning for references. Keep it to text/source so we
# don't read binaries; the reference token is plain text wherever it appears.
SCAN_EXTS = {".py", ".sh", ".yml", ".yaml", ".md", ".bats", ".js", ".ts"}

# Stopwords stripped before deriving heuristic keywords from a requirement, so
# an `inferred` match keys on the requirement's distinctive nouns, not on "the
# system must" boilerplate every FR shares.
_STOPWORDS = {
    "the", "a", "an", "must", "should", "may", "system", "and", "or", "of",
    "to", "in", "on", "for", "with", "that", "this", "it", "its", "be", "is",
    "are", "as", "by", "from", "when", "then", "given", "not", "no", "one",
    "each", "all", "any", "via", "per", "into", "at", "if", "iff", "than",
    "shall", "will", "can", "every", "run", "runs", "gate", "agent",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Requirement:
    """One parsed security requirement from a spec."""

    id: str               # canonical token, e.g. "FR-001", "SC-1", "AISVS-C3"
    kind: str             # "functional" | "success-criterion" | "aisvs"
    level: str            # "MUST" | "SHOULD" | "MAY" | "" (for SC/AISVS)
    text: str             # the requirement statement (one line, trimmed)
    keywords: list[str] = field(default_factory=list)


@dataclass
class CoverageRow:
    """A requirement mapped to whatever verification references it."""

    requirement: Requirement
    explicit_refs: list[str] = field(default_factory=list)   # repo-rel file paths
    inferred_refs: list[str] = field(default_factory=list)   # repo-rel file paths

    @property
    def status(self) -> str:
        if self.explicit_refs:
            return "covered"
        if self.inferred_refs:
            return "inferred"
        return "unmapped"


# ---------------------------------------------------------------------------
# Parsing — extract requirements from a spec (pure)
# ---------------------------------------------------------------------------

# Both spec styles in the wild:
#   **FR-001** — text...            (id alone in bold)
#   **FR-001**: text...
#   - **FR-001 — Short title.** longer text...   (id + title share one bold span)
# The id is the first thing inside the opening `**`; everything after it (whether
# the bold closes right after the id or wraps a title too) is the requirement body.
# `\d+` (not a digit cap): a cap + `\b` would make an over-length id like FR-12345
# fail the boundary and be DROPPED ENTIRELY — silently swallowing a requirement,
# the one thing a traceability tool must never do. `(?!\d)` ends the id at the last
# digit cleanly.
_FR_RE = re.compile(
    r"\*\*\s*(FR-\d+)(?!\d)(.*)", re.IGNORECASE
)
_SC_RE = re.compile(
    r"\*\*\s*(SC-\d+)(?!\d)(.*)", re.IGNORECASE
)
# Strip a leading separator / bold-close left over after the id is captured.
_LEAD_SEP_RE = re.compile(r"^\s*(?:\*\*)?\s*[—:\-]?\s*")
# AISVS chapter references in prose: "AISVS C3", "AISVS Chapter 3",
# "AISVS-3", "AISVS V3" — normalize all to "AISVS-C<n>".
_AISVS_RE = re.compile(
    r"AISVS[\s\-]*(?:chapter|ch\.?|v|c)?[\s\-]*(\d{1,2})", re.IGNORECASE
)
_LEVEL_RE = re.compile(r"\b(MUST NOT|MUST|SHOULD NOT|SHOULD|MAY)\b")


def _keywords(text: str, limit: int = 6) -> list[str]:
    """Distinctive lowercase keywords for a heuristic (inferred) match.

    Deterministic: lowercase, strip non-word chars, drop stopwords and short
    tokens, de-dup preserving order, cap at `limit`. Same text in => same
    keywords out.
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}", text.lower())
    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in _STOPWORDS or len(w) < 4 or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _normalize_aisvs(num: str) -> str:
    return f"AISVS-C{int(num)}"


def parse_spec(text: str) -> list[Requirement]:
    """Parse a spec's markdown into a deterministic, ordered requirement list.

    Extracts FR-NNN functional requirements, SC-N success criteria, and AISVS
    chapter references. De-dups by id (first occurrence wins — the definition
    line, not a later cross-reference). Order is: functional, then success
    criteria, then AISVS — stable across runs.
    """
    functional: list[Requirement] = []
    success: list[Requirement] = []
    aisvs: dict[str, Requirement] = {}
    seen_fr: set[str] = set()
    seen_sc: set[str] = set()

    for raw in text.splitlines():
        line = raw.strip()

        m = _FR_RE.search(line)
        if m:
            rid = m.group(1).upper()
            if rid not in seen_fr:
                seen_fr.add(rid)
                body = _clean(_LEAD_SEP_RE.sub("", m.group(2)))
                lvl = _LEVEL_RE.search(body)
                functional.append(Requirement(
                    id=rid, kind="functional",
                    level=(lvl.group(1) if lvl else ""),
                    text=body, keywords=_keywords(body),
                ))
            # an FR line can't also be an SC line; keep scanning for AISVS refs
        else:
            m = _SC_RE.search(line)
            if m:
                rid = m.group(1).upper()
                if rid not in seen_sc:
                    seen_sc.add(rid)
                    body = _clean(_LEAD_SEP_RE.sub("", m.group(2)))
                    success.append(Requirement(
                        id=rid, kind="success-criterion", level="",
                        text=body, keywords=_keywords(body),
                    ))

        # AISVS references can appear anywhere (prose, FR text, a mapping table).
        for am in _AISVS_RE.finditer(line):
            rid = _normalize_aisvs(am.group(1))
            if rid not in aisvs:
                aisvs[rid] = Requirement(
                    id=rid, kind="aisvs", level="",
                    text=f"AISVS chapter {int(am.group(1))} controls referenced by this spec.",
                    keywords=[],
                )

    return functional + success + list(aisvs.values())


def load_aisvs_labels(path: Path = AISVS_REGISTRY_PATH) -> dict[str, str]:
    """Read the flat `chapters: { C1: "...", ... }` map from the AISVS registry.

    Stdlib-only mini-parser (no pyyaml dependency, matching the other scripts'
    zero-dep test posture): we only need the simple `  C3: "Title"` lines under a
    `chapters:` key. Returns {} if the file is absent/unparseable — AISVS labels
    are a nicety, never a hard dependency.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    labels: dict[str, str] = {}
    in_chapters = False
    line_re = re.compile(r'^\s+(C\d{1,2})\s*:\s*"?(.*?)"?\s*$')
    for line in text.splitlines():
        if re.match(r"^chapters\s*:", line):
            in_chapters = True
            continue
        if in_chapters:
            if line and not line[0].isspace():
                break  # left the chapters block
            m = line_re.match(line)
            if m:
                labels[f"AISVS-{m.group(1)}"] = m.group(2).strip()
    return labels


def enrich_aisvs(requirements: list[Requirement], labels: dict[str, str]) -> None:
    """In place: replace each AISVS requirement's generic text with its chapter
    title when the registry knows it. No-op when labels is empty."""
    for r in requirements:
        if r.kind == "aisvs" and r.id in labels:
            r.text = f"AISVS chapter {r.id.removeprefix('AISVS-C')}: {labels[r.id]}"


def _clean(s: str) -> str:
    """Trim a requirement statement to one readable line: drop a trailing
    markdown bold close, collapse whitespace, strip a trailing period-less cut."""
    s = s.strip()
    # `**FR-001 — Title.** rest...` leaves a leading bold-close from the title.
    s = s.replace("**", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Reference index — scan the verification surface (pure given a file map)
# ---------------------------------------------------------------------------

def _ref_tokens(req: Requirement) -> list[str]:
    """The explicit-citation tokens that count as referencing this requirement.

    For FR/SC: the id with the canonical hyphen AND a compact form (FR001) so a
    test named `test_fr001_*` is matched. For AISVS: `AISVS C3` / `AISVS-C3` /
    `AISVS Chapter 3` all map back via the same regex used in parsing.
    """
    rid = req.id
    if req.kind == "aisvs":
        return [rid]  # matched specially via _AISVS_RE on the haystack
    compact = rid.replace("-", "")
    return [rid, compact]


def build_reference_index(files: dict[str, str]) -> dict[str, str]:
    """Map repo-relative path -> lowercased file content. Pure passthrough kept
    as a function so tests can inject a synthetic file map without disk I/O."""
    return {path: content for path, content in files.items()}


def match_requirement(
    req: Requirement, files: dict[str, str], spec_scope: set[str] | None = None
) -> CoverageRow:
    """Find explicit and inferred references to `req` across the scanned files.

    EXPLICIT: the requirement's literal id token (case-insensitive) appears in
    the file — an intentional citation. AUTHORITATIVE.
    INFERRED: no id token, but a strong keyword co-occurrence — a weak signal,
    reported but never counted as covered.

    SCOPE GUARD (no cross-spec collision): FR-NNN / SC-N ids are *spec-local* —
    every spec has an FR-001. So a bare `FR-001` token only counts as a citation
    of THIS spec when the file also references the spec's scope (its ticket id or
    filename stem, e.g. `sec-1234`). `spec_scope` has THREE states:
      - `None`        => guard OFF (back-compat for callers with a pre-scoped map).
      - a non-empty set => guard ON; a file must contain one of these tokens.
      - an EMPTY set  => guard ON but the spec produced no distinctive scope token
                         (e.g. a too-short stem, no ticket id) — so NO spec-local
                         id can be confidently scoped, and none are `covered`.
                         (Crucially NOT the same as `None`: an empty computed scope
                         must not silently re-disable the guard.)
    AISVS chapters are GLOBAL identifiers, so they are matched unscoped.
    """
    row = CoverageRow(requirement=req)
    tokens = [t.lower() for t in _ref_tokens(req)]
    guard_off = spec_scope is None
    scope = {s.lower() for s in (spec_scope or set())}

    for path, content in sorted(files.items()):
        lc = content.lower()

        explicit = False
        if req.kind == "aisvs":
            # Re-use the parse regex so "AISVS Chapter 3" in a test matches C3.
            for am in _AISVS_RE.finditer(content):
                if _normalize_aisvs(am.group(1)) == req.id:
                    explicit = True
                    break
        else:
            # Word-ish boundary so FR-001 doesn't match inside FR-0011 (trailing
            # digit) or FR-001a / FR001foo (trailing letter — matters for the
            # compact form). Leading guard rejects xFR-001.
            token_hit = any(
                re.search(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", lc)
                for tok in tokens
            )
            # Scoped: a spec-local id only counts when the file is talking about
            # THIS spec (its ticket id / stem appears too). guard_off => no guard;
            # an empty-but-present scope => nothing can be in scope.
            in_scope = guard_off or any(s in lc for s in scope)
            explicit = token_hit and in_scope

        if explicit:
            row.explicit_refs.append(path)
            continue

        # Inferred: a STRONG keyword co-occurrence — a clear majority of the
        # requirement's distinctive keywords appear in the file. A low bar (any
        # two common words) matches half the tree and makes the signal useless,
        # so require ceil(2/3 · N) hits with a floor of 3 (and never infer when
        # the requirement has too few keywords to corroborate). AISVS rows have
        # no keywords, so they never infer (explicit chapter citation only).
        if len(req.keywords) >= 3:
            need = max(3, -(-2 * len(req.keywords) // 3))  # ceil(2N/3), min 3
            hits = sum(1 for kw in req.keywords if kw in lc)
            if hits >= need:
                row.inferred_refs.append(path)

    return row


def build_matrix(
    requirements: list[Requirement], files: dict[str, str], spec_scope: set[str] | None = None
) -> list[CoverageRow]:
    return [match_requirement(r, files, spec_scope) for r in requirements]


# Ticket id (e.g. SEC-1234) anywhere in the spec path/stem — the durable scope key.
_TICKET_RE = re.compile(r"\b([A-Z]{2,5}-\d{2,6})\b", re.IGNORECASE)


def spec_scope_tokens(spec_rel: str) -> set[str]:
    """Scope tokens that tie a spec-local FR/SC id to THIS spec: its ticket id
    (sec-1234) and its filename stem. A test/control citing `FR-001` is read as
    covering this spec only when one of these also appears in the file.

    A scope token must be DISTINCTIVE: a tiny stem like `ai`/`v2` would substring-
    match nearly every file and collapse the guard back to "match everything", so
    we only trust stems of ≥6 chars (ticket ids like `sec-1234` are always ≥6)."""
    scope: set[str] = set()
    stem = Path(spec_rel).stem
    if len(stem) >= 6:
        scope.add(stem)
    for m in _TICKET_RE.finditer(spec_rel):
        scope.add(m.group(1))
    return {s for s in scope if s}


# ---------------------------------------------------------------------------
# Summary (pure)
# ---------------------------------------------------------------------------

def summarize(rows: list[CoverageRow]) -> dict:
    total = len(rows)
    covered = sum(1 for r in rows if r.status == "covered")
    inferred = sum(1 for r in rows if r.status == "inferred")
    unmapped = sum(1 for r in rows if r.status == "unmapped")
    # Coverage counts ONLY explicit references — no false-green from inferred.
    pct = round(100 * covered / total, 1) if total else 0.0
    return {
        "total": total,
        "covered": covered,
        "inferred": inferred,
        "unmapped": unmapped,
        "coverage_pct": pct,
    }


# ---------------------------------------------------------------------------
# Disk I/O + rendering (the thin impure shell)
# ---------------------------------------------------------------------------

def load_scan_files(root: Path, scan_dirs: tuple[str, ...]) -> dict[str, str]:
    files: dict[str, str] = {}
    for rel in scan_dirs:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_EXTS:
                continue
            try:
                files[str(path.relative_to(root))] = path.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                continue
    return files


def render_markdown(spec_rel: str, rows: list[CoverageRow], summary: dict) -> str:
    icon = {"covered": "✅", "inferred": "🟡", "unmapped": "❌"}
    out: list[str] = []
    out.append(f"# Requirements Traceability — `{spec_rel}`")
    out.append("")
    out.append(
        f"**{summary['covered']}/{summary['total']} requirements covered "
        f"({summary['coverage_pct']}%)** · {summary['inferred']} inferred · "
        f"{summary['unmapped']} unmapped"
    )
    out.append("")
    out.append("> Coverage counts **explicit** references only (a test/control that cites "
               "the requirement id). 🟡 inferred = keyword match, not yet a citation — "
               "review and confirm. ❌ unmapped = no linked test or control.")
    out.append("")
    out.append("| Requirement | Level | Status | Linked test / control |")
    out.append("|---|---|---|---|")
    for r in rows:
        req = r.requirement
        refs = r.explicit_refs or r.inferred_refs
        ref_txt = ", ".join(f"`{p}`" for p in refs) if refs else "—"
        level = req.level or "—"
        text = req.text if len(req.text) <= 90 else req.text[:87] + "…"
        out.append(
            f"| **{req.id}** — {text} | {level} | {icon[r.status]} {r.status} | {ref_txt} |"
        )
    out.append("")
    if summary["unmapped"]:
        out.append("## Unmapped requirements (the gap)")
        out.append("")
        for r in rows:
            if r.status == "unmapped":
                out.append(f"- **{r.requirement.id}** — {r.requirement.text}")
        out.append("")
    return "\n".join(out)


def to_dict(spec_rel: str, rows: list[CoverageRow], summary: dict) -> dict:
    return {
        "spec": spec_rel,
        "summary": summary,
        "rows": [
            {
                "id": r.requirement.id,
                "kind": r.requirement.kind,
                "level": r.requirement.level,
                "text": r.requirement.text,
                "status": r.status,
                "explicit_refs": r.explicit_refs,
                "inferred_refs": r.inferred_refs,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Tracer requirements-to-test traceability extractor.")
    ap.add_argument("--spec", required=True, help="Path to the spec markdown file.")
    ap.add_argument("--root", default=str(REPO_ROOT), help="Repo root to scan (default: this repo).")
    ap.add_argument("--scan-dir", action="append", default=None,
                    help="Directory to scan for references (repeatable). Defaults to tests/ + .github/workflows/.")
    ap.add_argument("--json", dest="json_out", help="Write the matrix JSON to this path.")
    ap.add_argument("--md", dest="md_out", help="Write the matrix markdown to this path.")
    ap.add_argument("--format", choices=("md", "json"), default="md",
                    help="What to print to stdout (default: md).")
    args = ap.parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = Path(args.root) / args.spec
    try:
        spec_text = spec_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Could not read spec {spec_path}: {e}", file=sys.stderr)
        return 2

    root = Path(args.root)
    spec_rel = str(spec_path.relative_to(root)) if str(spec_path).startswith(str(root)) else str(spec_path)

    requirements = parse_spec(spec_text)
    enrich_aisvs(requirements, load_aisvs_labels())
    if not requirements:
        print(f"No FR/SC/AISVS requirements parsed from {spec_rel} — nothing to trace.", file=sys.stderr)
        # Not a tool failure: an empty matrix is a valid (if uninteresting) report.
    scan_dirs = tuple(args.scan_dir) if args.scan_dir else DEFAULT_SCAN_DIRS
    files = load_scan_files(root, scan_dirs)

    scope = spec_scope_tokens(spec_rel)
    rows = build_matrix(requirements, files, scope)
    summary = summarize(rows)

    md = render_markdown(spec_rel, rows, summary)
    payload = to_dict(spec_rel, rows, summary)

    if args.md_out:
        Path(args.md_out).write_text(md + "\n", encoding="utf-8")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
