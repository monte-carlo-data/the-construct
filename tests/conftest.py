"""pytest configuration for the deterministic-script tests.

The scripts live in `.github/scripts/` (not an importable package), so this puts that
directory on `sys.path` for any test that wants a plain `import findings_validate`.
The ported tests that are also runnable standalone (`python3 tests/test_<name>.py`)
load their script via `importlib` from the repo-relative path instead; both styles
resolve the same files.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / ".github" / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
