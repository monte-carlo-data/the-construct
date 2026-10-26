# Tests

Unit tests for the deterministic scripts in [`.github/scripts/`](../.github/scripts/) — the
model-free cores behind `/tracer`, `/on-call`, `/hill-climb`, and the findings-ledger validator
that backs `/security-steve`. They need no API key and no network.

```bash
pip install -r requirements-dev.txt   # pytest is dev-only; PyYAML is needed by findings_validate.py / hill_climb.py
python3 -m pytest tests/ -q
```

`conftest.py` puts `.github/scripts/` on `sys.path`. `test_tracer_trace.py`, `test_oncall_triage.py`
and `test_hill_climb.py` are also runnable standalone (`python3 tests/test_<name>.py`) and need only
the standard library (plus PyYAML for hill-climb). The on-call tests replay the shipped fixture
`.github/scripts/fixtures/oncall/replay_example.json`; the hill-climb and validator tests also run
a live self-check over this repo's `findings/` docs and ledger.

`test_public_hygiene.py` is different from the rest: it scans every tracked text file for things that must never
reach a public template — real emails, account ids, tokens, Slack ids, UUIDs, workspace URLs, home-directory paths.
If it fails, fix the content; add an exact string to its `ALLOWED` set only for a deliberate, commented exception.
