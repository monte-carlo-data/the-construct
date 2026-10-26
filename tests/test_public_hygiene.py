"""Public-hygiene check: nothing that identifies a real organization, person, account, or
credential may land in this repository.

The Construct is a template. Every org-specific value is supposed to be a placeholder
(`your-org`, `example.com`, `123456789012`, `SEC-1234`), so the patterns below should never
match. When one does, fix the content — or, for a deliberate exception, add the exact
matched text to ALLOWED below with a comment saying why.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".txt", ".drawio", ".toml", ".cfg"}

# Files whose job is to *contain* these patterns.
SELF_EXCLUDED = {
    "tests/test_public_hygiene.py",
    ".github/scripts/sbom_validate.py",  # secret tripwire regexes
}

# Exact matched strings that are known-safe.
ALLOWED = {
    "123456789012",  # documentation AWS account id
    "security@your-org.com",
    "noreply@anthropic.com",
    "/home/runner/",  # GitHub-hosted runner home, used as test data for the path-leak detector
}

# Vendor documentation / login hosts that are not a tenant.
OKTA_PUBLIC_HOSTS = {"developer", "help", "login", "support", "trial", "www"}


def _okta_host_is_placeholder(hit: str) -> bool:
    host = hit.split(".okta.com")[0]
    return host.startswith(("your-", "example")) or host in OKTA_PUBLIC_HOSTS

CHECKS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("12-digit account id", re.compile(r"(?<![\w.-])\d{12}(?![\w.-])")),
    ("Slack channel/user id", re.compile(r"\b[CDUW]0[0-9A-Z]{8,10}\b")),
    ("UUID", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)),
    # Domain part must start with a letter so `package@1.2.3` version strings don't match.
    ("email outside example domains", re.compile(r"(?<![\w/])[\w.+-]+@(?!example\.(?:com|org|net)\b|your-org\b)[A-Za-z][\w-]*(?:\.[A-Za-z][\w-]*)+\b")),
    ("Linear workspace URL", re.compile(r"linear\.app/[A-Za-z0-9-]+/")),
    ("Notion page URL", re.compile(r"notion\.so/[A-Za-z0-9-]*[0-9a-f]{32}")),
    ("Okta org other than a placeholder", re.compile(r"(?<![\w-])[a-z0-9-]+\.okta\.com\b")),
    ("local home-directory path", re.compile(r"(?:/Users|/home)/[a-z][a-z0-9._-]+/")),
]


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    files = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode()
        if rel in SELF_EXCLUDED:
            continue
        p = ROOT / rel
        if p.suffix.lower() in TEXT_SUFFIXES and p.is_file():
            files.append(p)
    return files


def test_no_real_identifiers_or_credentials() -> None:
    files = _tracked_text_files()
    assert files, "git ls-files returned no text files — is this running inside the repo?"
    violations: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in CHECKS:
            for m in pattern.finditer(text):
                hit = m.group(0)
                if hit in ALLOWED:
                    continue
                if label.startswith("Okta") and _okta_host_is_placeholder(hit):
                    continue
                line = text.count("\n", 0, m.start()) + 1
                violations.append(f"{path.relative_to(ROOT)}:{line}: {label}: {hit!r}")
    assert not violations, "public-hygiene violations:\n  " + "\n  ".join(violations)
