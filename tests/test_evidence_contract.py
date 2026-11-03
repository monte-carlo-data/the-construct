#!/usr/bin/env python3
"""
Shared evidence contract tests. Stdlib only, no network.

Guards findings/EVIDENCE.md's one invariant (no eligible evidence can never ground `verified`),
the deterministic outcome of every fixture in findings/evidence/expected.json, the handoff chain
(ids, access and questions survive Analyst -> Concierge -> Tank/Oracle -> consolidation), the
generator's idempotence, and that schema.json cannot drift from the reference validator.

Run:  python3 tests/test_evidence_contract.py
"""

import copy
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

import evidence_fixtures as fx  # noqa: E402
import evidence_validate as ev  # noqa: E402

NOW = ev.parse_ts(fx.NOW)


def load(name: str) -> dict:
    return ev.load_json(ev.FIXTURES_DIR / name)


def policy(name: str) -> dict:
    return ev.load_json(ev.EVIDENCE_DIR / "policies" / name)


class VendoredFlat(unittest.TestCase):
    """The module is vendored byte-for-byte into agent images at /app/<name>.py, where its own path
    has only two parents. Root resolution must never raise there: an IndexError at import takes
    down every service that vendors the file."""

    def test_root_resolves_in_place_and_flat(self):
        in_place = REPO_ROOT / ".github" / "scripts" / "evidence_validate.py"
        self.assertEqual(ev.repo_root_for(in_place), REPO_ROOT)
        self.assertEqual(ev.repo_root_for(Path("/app/evidence_contract.py")), Path("/app"))
        self.assertEqual(ev.repo_root_for(Path("/evidence_contract.py")), Path("/"))

    def test_module_imports_from_a_flat_directory(self):
        import shutil
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            app = Path(d) / "app"
            app.mkdir()
            shutil.copy(REPO_ROOT / ".github" / "scripts" / "evidence_validate.py", app / "evidence_contract.py")
            proc = subprocess.run(
                [sys.executable, "-I", "-c",
                 f"import sys; sys.path.insert(0, {str(app)!r}); import evidence_contract as c; print(c.REPO_ROOT)"],
                cwd=app, capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), str(app.resolve()))


class FixturesReplay(unittest.TestCase):
    def test_every_fixture_matches_its_pinned_outcome(self):
        self.assertEqual(ev.run_fixtures(), [])

    def test_generator_is_idempotent(self):
        self.assertEqual(fx.main(["--check"]), 0)

    def test_expected_json_pins_every_fixture_on_disk(self):
        expected = ev.load_json(ev.EXPECTED_JSON)
        on_disk = {p.relative_to(ev.FIXTURES_DIR).as_posix() for p in ev.FIXTURES_DIR.rglob("*.json")}
        self.assertEqual(on_disk, set(expected["fixtures"]))
        self.assertGreaterEqual(len(on_disk), 19)


class Invariant(unittest.TestCase):
    """Missing evidence is an explicit partial/insufficient result, never a verified conclusion."""

    def test_no_eligible_evidence_never_grounds_verified_across_all_fixtures(self):
        expected = ev.load_json(ev.EXPECTED_JSON)
        for name, spec in expected["fixtures"].items():
            pol = policy(spec["policy"].split("/")[-1]) if spec.get("policy") else None
            result = ev.validate(load(name), receiver=spec["receiver"], policy=pol, now=NOW)
            if result["outcome"] == "accepted" and not result["eligible_ids"]:
                self.assertEqual(result["grounding"], "insufficient", name)
            if result["outcome"] == "rejected":
                self.assertEqual(result["grounding"], "insufficient", name)

    def test_empty_items_with_declared_supported_claim_is_insufficient(self):
        b = load("missing-evidence-insufficient.json")
        result = ev.validate(b, receiver="concierge", now=NOW)
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["claims"]["c1"], "unresolved")
        self.assertEqual(result["grounding"], "insufficient")
        self.assertTrue(any("declared supported, computed unresolved" in w for w in result["warnings"]))

    def test_declared_coverage_can_lower_but_never_raise_grounding(self):
        b = load("valid-live-observation.json")
        self.assertEqual(ev.validate(b, receiver="analyst", now=NOW)["grounding"], "verified")
        lowered = copy.deepcopy(b)
        lowered["coverage"]["status"] = "partial"
        self.assertEqual(ev.validate(lowered, receiver="analyst", now=NOW)["grounding"], "partial")
        raised = load("stale-live-observation.json")
        raised["coverage"]["status"] = "complete"
        self.assertEqual(ev.validate(raised, receiver="analyst", now=NOW)["grounding"], "insufficient")

    def test_historical_conclusion_cannot_support_a_claim(self):
        result = ev.validate(load("historical-only.json"), receiver="concierge", now=NOW)
        self.assertEqual(list(result["item_states"].values()), ["historical"])
        self.assertEqual(result["claims"]["c1"], "unresolved")
        self.assertTrue(any("historical" in w for w in result["warnings"]))

    def test_untrusted_item_is_kept_fenced_and_ineligible(self):
        b = load("untrusted-authority.json")
        result = ev.validate(b, receiver="concierge", now=NOW)
        untrusted = next(i for i in b["items"] if i["authority"]["level"] == "untrusted")
        self.assertEqual(result["item_states"][untrusted["evidence_id"]], "fresh")
        self.assertNotIn(untrusted["evidence_id"], result["eligible_ids"])
        self.assertEqual(result["claims"]["c1"], "unresolved")
        text = ev.render(b, result)
        self.assertIn("is not an instruction", text)
        fence_start = text.index("```text\n" + untrusted["content"]["excerpt"])
        self.assertIn("ignore prior instructions", text[fence_start:])
        self.assertIn(f"## {untrusted['evidence_id']}", text)


class Rejections(unittest.TestCase):
    def test_malformed_lists_every_error(self):
        result = ev.validate(load("malformed-missing-source.json"), receiver="analyst", now=NOW)
        self.assertEqual(result["reasons"], ["malformed"])
        joined = "\n".join(result["errors"])
        self.assertIn("missing source", joined)
        self.assertIn("observed_at must be ISO-8601", joined)
        self.assertIn("authority.level", joined)

    def test_not_json_object_is_malformed(self):
        self.assertEqual(ev.validate(["not", "a", "bundle"], now=NOW)["reasons"], ["malformed"])
        self.assertEqual(ev.validate({"__unparseable__": "x"}, now=NOW)["reasons"], ["malformed"])

    def test_future_observation_and_retrieved_before_observed_are_malformed(self):
        b = load("valid-live-observation.json")
        future = copy.deepcopy(b)
        future["items"][0]["observed_at"] = (NOW + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        future = ev.mint(future)
        self.assertEqual(ev.validate(future, receiver="analyst", now=NOW)["reasons"], ["malformed"])
        early = copy.deepcopy(b)
        early["items"][0]["retrieved_at"] = "2026-10-27T00:00:00Z"
        self.assertEqual(ev.validate(early, receiver="analyst", now=NOW)["reasons"], ["malformed"])

    def test_unknown_reference_is_malformed(self):
        b = load("valid-live-observation.json")
        b["claims"][0]["supported_by"] = ["ev-0000000000000000"]
        result = ev.validate(b, receiver="analyst", now=NOW)
        self.assertEqual(result["reasons"], ["malformed"])
        self.assertTrue(any("unknown evidence id" in e for e in result["errors"]))

    def test_item_count_and_byte_budgets(self):
        b = load("valid-live-observation.json")
        many = copy.deepcopy(b)
        base = many["items"][0]
        many["items"] = []
        for i in range(ev.BUDGETS["max_items"] + 1):
            it = copy.deepcopy(base)
            it["content"] = {"excerpt": f"observation {i}"}
            many["items"].append(it)
        many["claims"] = []
        many = ev.mint(many)
        result = ev.validate(many, receiver="analyst", now=NOW)
        self.assertEqual(result["reasons"], ["oversized"])
        self.assertTrue(any("items >" in e for e in result["errors"]))

        big = copy.deepcopy(b)
        big["items"] = []
        for i in range(40):
            it = copy.deepcopy(base)
            it["content"] = {"excerpt": ("%02d" % i) * 990}  # 1980 chars, under the excerpt cap
            big["items"].append(it)
        big["claims"] = []
        big = ev.mint(big)
        result = ev.validate(big, receiver="analyst", now=NOW)
        self.assertEqual(result["reasons"], ["oversized"])
        self.assertTrue(any("bytes >" in e for e in result["errors"]))

    def test_policy_may_not_assume_missing_evidence(self):
        bad = policy("tank.json")
        bad["insufficient_evidence"] = "assume"
        result = ev.validate(load("policy-gap.json"), receiver="tank", policy=bad, now=NOW)
        self.assertEqual(result["reasons"], ["malformed"])
        self.assertTrue(any('insufficient_evidence must be "partial"' in e for e in result["errors"]))
        self.assertEqual(ev.check_policy(policy("tank.json")), [])
        self.assertEqual(ev.check_policy(policy("oracle.json")), [])


class Ids(unittest.TestCase):
    def test_id_is_content_addressed_and_scope_order_independent(self):
        item = fx.panther_alert_item()
        item["scope"]["resources"] = ["b", "a", "a"]
        a = ev.evidence_id_for(item)
        item["scope"]["resources"] = ["a", "b"]
        self.assertEqual(a, ev.evidence_id_for(item))
        item["content"]["excerpt"] += "."
        self.assertNotEqual(a, ev.evidence_id_for(item))
        item["retrieved_at"] = "2026-10-27T17:59:59Z"  # outside the identity
        self.assertEqual(ev.evidence_id_for(item), ev.evidence_id_for(ev.mint({"items": [item]})["items"][0]))
        self.assertRegex(a, r"^ev-[0-9a-f]{16}$")

    def test_mint_resolves_local_handles_in_claims_and_questions(self):
        # A persona cannot compute ids, so it names its new items "new:<handle>" and cites the handle.
        a, b = fx.panther_alert_item(), fx.panther_alert_item()
        b["content"]["excerpt"] += " (second read)"
        a["evidence_id"], b["evidence_id"] = "new:alert", "new:pivot"
        raw = {"items": [a, b],
               "claims": [{"claim_id": "c1", "statement": "s", "status": "unresolved",
                           "supported_by": ["new:alert"], "contradicted_by": ["new:pivot"]}],
               "questions": [{"question_id": "q1", "text": "t", "raised_by": "analyst", "status": "answered",
                              "about": ["new:alert", "new:pivot"], "answer_evidence": ["new:pivot"]}]}
        out = ev.mint(raw)
        ia, ib = ev.evidence_id_for(a), ev.evidence_id_for(b)
        self.assertEqual([i["evidence_id"] for i in out["items"]], [ia, ib])
        self.assertEqual(out["claims"][0]["supported_by"], [ia])
        self.assertEqual(out["claims"][0]["contradicted_by"], [ib])
        self.assertEqual(out["questions"][0]["about"], [ia, ib])
        self.assertEqual(out["questions"][0]["answer_evidence"], [ib])
        self.assertEqual(raw["claims"][0]["supported_by"], ["new:alert"])  # input untouched

    def test_mint_leaves_ambiguous_or_unknown_handles_for_validate_to_reject(self):
        a, b = fx.panther_alert_item(), fx.panther_alert_item()
        b["content"]["excerpt"] += "."
        a["evidence_id"] = b["evidence_id"] = "new:dup"
        raw = {"items": [a, b], "claims": [{"claim_id": "c1", "statement": "s", "status": "unresolved",
                                            "supported_by": ["new:dup", "new:nope"], "contradicted_by": []}]}
        self.assertEqual(ev.mint(raw)["claims"][0]["supported_by"], ["new:dup", "new:nope"])
        errors = ev.check_structure(ev.mint(raw))
        self.assertTrue(any("unknown evidence id new:dup" in e for e in errors))

    def test_tampered_content_with_kept_id_is_rejected(self):
        result = ev.validate(load("tampered-id.json"), receiver="analyst", now=NOW)
        self.assertEqual(result["reasons"], ["id_mismatch"])

    def test_expires_at_beats_type_freshness(self):
        b = load("valid-live-observation.json")
        b["items"][0]["expires_at"] = "2026-10-27T17:00:00Z"  # before NOW, item itself is only ~1h old
        result = ev.validate(b, receiver="analyst", now=NOW)
        self.assertEqual(result["item_states"][b["items"][0]["evidence_id"]], "expired")


class HandoffChain(unittest.TestCase):
    """Analyst -> Concierge -> Tank / Oracle -> consolidated: ids, access and questions survive."""

    def setUp(self):
        self.b01 = load("handoff/01-analyst-to-concierge.json")
        self.b02a = load("handoff/02a-concierge-to-tank.json")
        self.b02b = load("handoff/02b-concierge-to-oracle.json")
        self.b03a = load("handoff/03a-tank-reply.json")
        self.b03b = load("handoff/03b-oracle-reply.json")
        self.b04 = load("handoff/04-concierge-consolidated.json")
        self.ids01 = {i["evidence_id"]: ev.canonical_json(i) for i in self.b01["items"]}
        self.bedrock_id = next(i["evidence_id"] for i in self.b01["items"] if i["source"]["system"] == "bedrock")

    def test_every_id_and_question_from_01_survives_to_04(self):
        ids04 = {i["evidence_id"]: ev.canonical_json(i) for i in self.b04["items"]}
        for eid, canon in self.ids01.items():
            self.assertIn(eid, ids04)
            self.assertEqual(canon, ids04[eid], "item mutated in transit")
        self.assertEqual({q["question_id"] for q in self.b01["questions"]} - {q["question_id"] for q in self.b04["questions"]}, set())
        self.assertEqual({c["claim_id"] for c in self.b01["claims"]} - {c["claim_id"] for c in self.b04["claims"]}, set())

    def test_relay_to_oracle_strips_bedrock_and_records_redaction(self):
        self.assertNotIn(self.bedrock_id, {i["evidence_id"] for i in self.b02b["items"]})
        self.assertIn(self.bedrock_id, {r["evidence_id"] for r in self.b02b["redactions"]})
        self.assertEqual(self.b02b["receiver"], "oracle")
        for claim in self.b02b["claims"]:
            self.assertNotIn(self.bedrock_id, claim["supported_by"] + claim["contradicted_by"])
        for q in self.b02b["questions"]:
            self.assertNotIn(self.bedrock_id, q["about"])
        # and tank, which is cleared, keeps it
        self.assertIn(self.bedrock_id, {i["evidence_id"] for i in self.b02a["items"]})
        # nothing addressed to oracle ever carries it
        for b in (self.b02b, self.b03b):
            self.assertNotIn(self.bedrock_id, {i["evidence_id"] for i in b["items"]})
        self.assertEqual(ev.validate(self.b02b, receiver="oracle", now=NOW)["outcome"], "accepted")

    def test_hops_are_monotonic(self):
        prefix = self.b01["hops"]
        for b in (self.b02a, self.b02b, self.b03a, self.b03b):
            self.assertEqual(b["hops"][:len(prefix)], prefix)
            self.assertGreater(len(b["hops"]), len(prefix))
        agents04 = [h["agent"] for h in self.b04["hops"]]
        for agent in ("analyst", "concierge", "tank", "oracle"):
            self.assertIn(agent, agents04)
        self.assertEqual(agents04[-1], "concierge")

    def test_consolidated_answers_questions_and_keeps_the_unsupported_claim_unresolved(self):
        result = ev.validate(self.b04, receiver="analyst", now=NOW)
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["questions"], {"q1": "answered", "q2": "answered"})
        self.assertEqual(result["claims"], {"c1": "unresolved", "c2": "supported"})
        self.assertEqual(result["not_covered"], ["exposure.external_scan", "identity.privilege"])
        self.assertEqual(result["grounding"], "partial")
        self.assertEqual(len(self.b04["items"]), 6)
        self.assertIn(self.bedrock_id, {r["evidence_id"] for r in self.b04.get("redactions", [])})

    def test_merge_is_the_reference_consolidation(self):
        merged = ev.merge([self.b01, self.b03a, self.b03b], bundle_id=self.b04["bundle_id"], producer="concierge",
                          receiver="analyst", created_at=self.b04["created_at"], request_id=self.b04["request_id"])
        merged["hops"].append(self.b04["hops"][-1])
        self.assertEqual(ev.canonical_json(merged), ev.canonical_json(self.b04))
        # merging the same bundle twice changes nothing: dedup is by id
        twice = ev.merge([self.b01, self.b01], bundle_id="x", producer="concierge", receiver="analyst",
                         created_at=self.b04["created_at"])
        self.assertEqual(len(twice["items"]), len(self.b01["items"]))

    def test_policy_gap_closes_when_the_owning_specialist_replies(self):
        before = ev.validate(self.b02a, receiver="tank", policy=policy("tank.json"), now=NOW)
        self.assertIn("vuln.presence", before["not_covered"])
        after = ev.validate(self.b03a, receiver="tank", policy=policy("tank.json"), now=NOW)
        self.assertNotIn("vuln.presence", after["not_covered"])

    def test_relay_refuses_a_rejected_bundle_unchanged(self):
        tampered = load("tampered-id.json")
        out, result = ev.relay(tampered, from_agent="concierge", to_agent="tank", request_id="r", at=fx.NOW, now=NOW)
        self.assertEqual(result["outcome"], "rejected")
        self.assertIs(out, tampered)


class ReplayScenarios(unittest.TestCase):
    """The five synthetic pilot investigations: each pinned outcome matches its intent."""

    def _run(self, name, receiver, policy_name=None):
        pol = policy(policy_name) if policy_name else None
        return ev.validate(load(name), receiver=receiver, policy=pol, now=NOW)

    def test_oracle_scope_expansion_asks_only_for_the_uncovered_axis(self):
        result = self._run("replay/oracle-scope-expansion.json", "oracle", "oracle.json")
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["grounding"], "partial")
        self.assertEqual(result["not_covered"], ["exposure.ownership"])
        self.assertEqual(list(result["item_states"].values()), ["fresh"])

    def test_stale_live_telemetry_is_marked_and_reopens_its_axis(self):
        b = load("replay/stale-live-telemetry.json")
        result = ev.validate(b, receiver="oracle", policy=policy("oracle.json"), now=NOW)
        stale = [eid for eid, s in result["item_states"].items() if s == "stale"]
        self.assertEqual(len(stale), 1)
        self.assertEqual(result["claims"]["c1"], "unresolved")
        self.assertEqual(result["not_covered"], ["exposure.traffic"])
        self.assertEqual(result["grounding"], "partial")
        self.assertIn(f"## {stale[0]} · live_observation · panther · stale", ev.render(b, result))

    def test_conflicting_observations_keep_both_items_and_contradict_the_claim(self):
        result = self._run("replay/conflicting-observations.json", "concierge")
        self.assertEqual(set(result["item_states"].values()), {"fresh"})
        self.assertEqual(result["contradicted_claims"], ["c1"])
        self.assertEqual(result["questions"], {"q2": "open"})
        self.assertEqual(result["grounding"], "partial")

    def test_unavailable_sensor_is_an_explicit_gap_under_the_analyst_policy(self):
        self.assertEqual(ev.check_policy(policy("analyst.json")), [])
        result = self._run("replay/unavailable-sensor.json", "analyst", "analyst.json")
        self.assertEqual(set(result["item_states"].values()), {"fresh"})
        self.assertEqual(result["not_covered"], ["saas.authorization"])
        self.assertEqual(result["grounding"], "partial")

    def test_denied_evidence_never_reaches_tank(self):
        b = load("replay/denied-evidence.json")
        result = ev.validate(b, receiver="tank", policy=policy("tank.json"), now=NOW)
        denied = [eid for eid, s in result["item_states"].items() if s == "denied"]
        self.assertEqual(len(denied), 1)
        self.assertEqual(result["claims"], {"c1": "unresolved", "c2": "supported"})
        self.assertEqual(result["not_covered"], [])
        stripped = ev.strip_denied(b, result)
        self.assertNotIn(denied[0], {i["evidence_id"] for i in stripped["items"]})
        self.assertIn(denied[0], {r["evidence_id"] for r in stripped["redactions"]})
        for claim in stripped["claims"]:
            self.assertNotIn(denied[0], claim["supported_by"] + claim["contradicted_by"])
        self.assertEqual(ev.validate(stripped, receiver="tank", policy=policy("tank.json"), now=NOW)["outcome"], "accepted")


class SchemaAgreesWithValidator(unittest.TestCase):
    """schema.json is what other repos may validate with; it must say what the validator does."""

    def setUp(self):
        self.schema = ev.load_json(ev.EVIDENCE_DIR / "schema.json")
        self.policy_schema = ev.load_json(ev.EVIDENCE_DIR / "policy.schema.json")
        self.defs = self.schema["$defs"]

    def test_required_fields(self):
        self.assertEqual(set(self.schema["required"]), set(ev.BUNDLE_REQUIRED))
        self.assertEqual(set(self.defs["item"]["required"]), set(ev.ITEM_REQUIRED))
        self.assertEqual(set(self.defs["source"]["required"]), set(ev.SOURCE_REQUIRED))
        self.assertEqual(set(self.defs["authority"]["required"]), set(ev.AUTHORITY_REQUIRED))
        self.assertEqual(set(self.defs["claim"]["required"]), set(ev.CLAIM_REQUIRED))
        self.assertEqual(set(self.defs["question"]["required"]), set(ev.QUESTION_REQUIRED))
        self.assertEqual(set(self.defs["hop"]["required"]), set(ev.HOP_REQUIRED))

    def test_enums_and_version(self):
        self.assertEqual(self.schema["properties"]["contract_version"]["const"], ev.CONTRACT_VERSION)
        self.assertEqual(self.defs["item"]["properties"]["type"]["enum"], list(ev.EVIDENCE_TYPES))
        self.assertEqual(self.defs["authority"]["properties"]["level"]["enum"], list(ev.AUTHORITY_LEVELS))
        self.assertEqual(self.defs["authority"]["properties"]["access"]["enum"], list(ev.ACCESS_MODES))
        self.assertEqual(self.defs["claim"]["properties"]["status"]["enum"], list(ev.CLAIM_STATUSES))
        self.assertEqual(self.defs["question"]["properties"]["status"]["enum"], list(ev.QUESTION_STATUSES))
        self.assertEqual(self.defs["coverage"]["properties"]["status"]["enum"], list(ev.COVERAGE_STATUSES))
        self.assertEqual(self.policy_schema["properties"]["insufficient_evidence"]["const"], "partial")

    def test_budgets(self):
        props = self.schema["properties"]
        self.assertEqual(props["items"]["maxItems"], ev.BUDGETS["max_items"])
        self.assertEqual(props["claims"]["maxItems"], ev.BUDGETS["max_claims"])
        self.assertEqual(props["questions"]["maxItems"], ev.BUDGETS["max_questions"])
        self.assertEqual(props["hops"]["maxItems"], ev.BUDGETS["max_hops"])
        excerpt = self.defs["content"]["oneOf"][0]["properties"]["excerpt"]["maxLength"]
        self.assertEqual(excerpt, ev.BUDGETS["max_excerpt_chars"])

    def test_fixture_ids_match_the_documented_pattern(self):
        pattern = self.defs["evidence_id"]["pattern"]
        for p in ev.FIXTURES_DIR.rglob("*.json"):
            if p.name.startswith("malformed"):
                continue
            for item in ev.load_json(p)["items"]:
                self.assertRegex(item["evidence_id"], pattern, p.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
