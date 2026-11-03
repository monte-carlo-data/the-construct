#!/usr/bin/env python3
"""
Retrieval and evidence-grounding eval tests. Stdlib only, no network, no secrets.

Proves the scorer fails on the failure classes it exists to catch (unauthorized evidence, citations
to nothing, a plausible answer grounded in the wrong source, injected instructions, ...), that every
corpus case has a passing baseline, a passing candidate and a failing wrong-source record, that the
pinned scores match, and that compare refuses an unreviewed thresholds file and decides small-n runs
on gates and per-run bars.

Run:  python3 tests/test_evidence_eval.py
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

import evidence_eval as ee  # noqa: E402
import evidence_fixtures as fx  # noqa: E402
import evidence_validate as ev  # noqa: E402

CASES = ee.load_cases(ee.CASES_DIR)
EXPECTED_SCORES = ev.load_json(ee.EVALS_DIR / "expected-scores.json")["scores"]
REVIEWED = {"by": "unit-test", "date": "2026-10-28"}


def record(name: str) -> dict:
    return ev.load_json(ee.RECORDS_DIR / f"{name}.json")


def score(name: str, rec: dict | None = None) -> dict:
    rec = rec if rec is not None else record(name)
    return ee.score_record(CASES.get(rec.get("case_id")), rec)


def thresholds(**reviewed) -> dict:
    t = ev.load_json(ee.THRESHOLDS_JSON)
    t["reviewed"] = dict(t["reviewed"], **reviewed)
    return t


def results_for(label: str, cases=None) -> dict:
    names = [f"{cid}/{label}" for cid in (cases or sorted(CASES))]
    return {"results": {n: score(n) for n in names}}


class Corpus(unittest.TestCase):
    def test_scores_match_the_pinned_expected_scores(self):
        for name, pinned in EXPECTED_SCORES.items():
            with self.subTest(record=name):
                self.assertEqual(score(name), pinned)

    def test_generator_is_idempotent_including_evals(self):
        self.assertEqual(fx.main(["--check"]), 0)

    def test_every_case_has_passing_baseline_and_candidate_and_a_failing_wrong_source(self):
        for cid in CASES:
            with self.subTest(case=cid):
                self.assertTrue(EXPECTED_SCORES[f"{cid}/baseline"]["pass"], EXPECTED_SCORES[f"{cid}/baseline"]["gates"])
                self.assertTrue(EXPECTED_SCORES[f"{cid}/candidate"]["pass"], EXPECTED_SCORES[f"{cid}/candidate"]["gates"])
                self.assertEqual(list(EXPECTED_SCORES[f"{cid}/bad-wrong-source"]["gates"]), ["G7"])

    def test_every_bad_record_fails_and_every_good_one_passes(self):
        for name, s in EXPECTED_SCORES.items():
            with self.subTest(record=name):
                self.assertEqual(s["pass"], not name.split("/")[1].startswith("bad-"))

    def test_every_ticket_category_is_covered(self):
        required = {"exact_lookup_cve", "exact_lookup_arn", "exact_lookup_repository", "exact_lookup_ticket",
                    "paraphrased_question", "ambiguous_scope", "missing_facts", "stale_evidence",
                    "contradictory_evidence", "deleted_source", "permission_denial", "malicious_instruction",
                    "budget_exhaustion", "oracle_consult_replay"}
        self.assertEqual(required - {c["category"] for c in CASES.values()}, set())

    def test_paraphrase_shares_its_exact_cases_expected_set(self):
        for c in CASES.values():
            if c["paraphrase_of"]:
                with self.subTest(case=c["case_id"]):
                    self.assertEqual(c["expected"], CASES[c["paraphrase_of"]]["expected"])

    def test_existing_contract_fixtures_are_untouched_by_the_evals(self):
        # The evals use their own inputs dir; expected.json still pins exactly the 24 contract fixtures.
        self.assertEqual(len(ev.load_json(ev.EXPECTED_JSON)["fixtures"]), 24)


class Gates(unittest.TestCase):
    """One assertion per gate on a record a plausible run could produce (Story 1)."""

    def gates(self, name, rec=None):
        return set(score(name, rec)["gates"])

    def test_g1_withheld_excerpt_found_in_workdir(self):
        self.assertIn("G1", self.gates("permission-denial/bad-leak-in-workdir"))

    def test_g1_citing_an_item_denied_to_the_receiver(self):
        self.assertIn("G1", self.gates("permission-denial/bad-cites-denied"))

    def test_g2_citing_an_id_that_is_not_in_hand(self):
        rec = record("exact-cve/candidate")
        rec["conclusions"][0]["cites"] = ["ev-0000000000000000"]
        self.assertEqual(self.gates(None, rec), {"G2"})

    def test_g2_citing_from_a_rejected_bundle(self):
        self.assertEqual(self.gates("budget-exhaustion/bad-cites-rejected-bundle"), {"G2"})

    def test_g3_stale_item_as_current_support(self):
        self.assertEqual(self.gates("stale-evidence/bad-stale-as-current"), {"G3"})

    def test_g3_is_not_raised_when_the_stale_item_is_hedged(self):
        rec = record("stale-evidence/bad-stale-as-current")
        rec["conclusions"][0]["hedged"] = True
        self.assertEqual(self.gates(None, rec), set())

    def test_g3_expired_deleted_source(self):
        self.assertIn("G3", self.gates("deleted-source/bad-cites-deleted-source"))

    def test_g4_answering_outright_on_a_partial_case(self):
        self.assertEqual(self.gates("contradictory-evidence/bad-picks-one-scanner"), {"G4"})
        self.assertEqual(self.gates("ambiguous-scope/bad-picks-one-account"), {"G4"})

    def test_g4_stating_verified_when_its_own_bundle_is_partial(self):
        rec = record("stale-evidence/candidate")
        rec["grounding_stated"] = "verified"
        reasons = score(None, rec)["gates"]["G4"]
        self.assertTrue(any("own bundle" in r for r in reasons), reasons)

    def test_g5_forbidden_full_scan_in_an_oracle_consult(self):
        self.assertEqual(self.gates("oracle-consult/bad-full-scan"), {"G5"})

    def test_g6_injected_instruction_followed(self):
        self.assertIn("G6", self.gates("injected-instruction/bad-follows-injection"))

    def test_g7_right_verdict_wrong_source_fails_even_when_verdict_matches(self):
        s = score("exact-repo/bad-wrong-source")
        self.assertTrue(s["metrics"]["verdict_ok"])
        self.assertEqual(set(s["gates"]), {"G7"})

    def test_g7_plausible_prose_answer_from_an_untrusted_page(self):
        s = score("exact-cve/bad-untrusted-source")
        self.assertTrue(s["metrics"]["verdict_ok"])
        self.assertEqual(set(s["gates"]), {"G7"})

    def test_g8_unknown_case_missing_fields_and_incomplete_revisions(self):
        rec = record("exact-cve/candidate")
        unknown = dict(rec, case_id="no-such-case")
        self.assertEqual(set(ee.score_record(None, unknown)["gates"]), {"G8"})
        for field in ("withheld_ids_found", "sensor_calls", "conclusions"):
            broken = copy.deepcopy(rec)
            del broken[field]
            with self.subTest(missing=field):
                self.assertEqual(set(score(None, broken)["gates"]), {"G8"})
        rec["revisions"] = dict(rec["revisions"], image="")
        self.assertEqual(set(score(None, rec)["gates"]), {"G8"})

    def test_g8_mode_on_without_a_bundle(self):
        rec = record("exact-cve/candidate")
        rec["bundle"] = None
        self.assertEqual(set(score(None, rec)["gates"]), {"G8"})

    def test_g8_unreadable_record_file_fails_score(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "broken.json").write_text("{not json", encoding="utf-8")
            out = ee.score(CASES, [d])
        self.assertEqual(len(out["summary"]["failed"]), 1)
        (only,) = out["results"].values()
        self.assertEqual(set(only["gates"]), {"G8"})
        self.assertIsNone(only["metrics"])


class Metrics(unittest.TestCase):
    def test_baseline_and_candidate_are_scored_on_the_same_source_keys(self):
        b, c = score("oracle-consult/baseline")["metrics"], score("oracle-consult/candidate")["metrics"]
        self.assertEqual(b["recall"], 1.0)
        self.assertEqual(c["recall"], 1.0)
        self.assertIsNone(b["citation_validity"])  # no ids on the prose path
        self.assertEqual(c["citation_validity"], 1.0)

    def test_oracle_consult_baseline_duplicate_and_out_of_scope_reads_are_counted(self):
        b, c = score("oracle-consult/baseline")["metrics"], score("oracle-consult/candidate")["metrics"]
        self.assertEqual(b["duplicate_calls"], 1)  # Analyst and Oracle both read the same Panther alert
        self.assertEqual(b["over_budget_keys"], [fx.PANTHER_ALERT])
        self.assertEqual(b["out_of_scope_reads"], 1)  # Oracle wandered into Aikido
        self.assertEqual((c["duplicate_calls"], c["out_of_scope_reads"]), (0, 0))

    def test_correct_abstention_is_not_penalised_on_recall_but_a_silent_gap_is_counted(self):
        good, bad = score("missing-facts/candidate")["metrics"], score("missing-facts/bad-asserts-without-evidence")["metrics"]
        self.assertIsNone(good["recall"])
        self.assertEqual(good["silent_gaps"], 0)
        self.assertEqual(bad["silent_gaps"], 1)
        self.assertEqual(bad["unsupported_conclusions"], 1)

    def test_record_schema_agrees_with_the_scorer_and_has_no_text_field(self):
        schema = ev.load_json(ee.EVALS_DIR / "record.schema.json")
        self.assertEqual(set(schema["required"]), set(ee.RECORD_REQUIRED))
        self.assertEqual(set(schema["properties"]["revisions"]["required"]), set(ee.REVISION_REQUIRED))
        concl = schema["properties"]["conclusions"]["items"]
        self.assertEqual(set(concl["required"]), set(ee.CONCLUSION_REQUIRED))
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(concl["additionalProperties"])
        for props in (schema["properties"], concl["properties"]):
            self.assertFalse({"text", "excerpt", "answer", "summary"} & set(props))

    def test_every_corpus_record_and_case_uses_only_schema_fields(self):
        rec_props = set(ev.load_json(ee.EVALS_DIR / "record.schema.json")["properties"])
        case_schema = ev.load_json(ee.EVALS_DIR / "case.schema.json")
        for p in ee.RECORDS_DIR.rglob("*.json"):
            with self.subTest(record=p.name):
                self.assertLessEqual(set(ev.load_json(p)), rec_props)
        for c in CASES.values():
            with self.subTest(case=c["case_id"]):
                self.assertEqual(set(c), set(case_schema["required"]))
                self.assertEqual(set(c["expected"]), set(case_schema["properties"]["expected"]["required"]))


class Compare(unittest.TestCase):
    def test_refuses_an_unreviewed_thresholds_file(self):
        with self.assertRaisesRegex(ValueError, "reviewed.by"):
            ee.compare(results_for("baseline"), results_for("candidate"), thresholds(by=None, date=None))

    def test_shipped_thresholds_carry_a_human_review(self):
        # Signed before any operational run was scored. A value change needs a new review.
        shipped = ev.load_json(ee.THRESHOLDS_JSON)["reviewed"]
        self.assertTrue(shipped["by"] and shipped["date"])

    def test_synthetic_baseline_vs_candidate_passes_with_aggregates_enforced(self):
        cmp = ee.compare(results_for("baseline"), results_for("candidate"), thresholds(**REVIEWED))
        self.assertTrue(cmp["pass"], json.dumps(cmp, indent=1))
        self.assertTrue(cmp["aggregates_enforced"])  # 14 cases >= small_n
        dup = next(a for a in cmp["aggregate"] if a["measure"] == "duplicate sensor calls")
        self.assertEqual((dup["baseline"], dup["candidate"]), (1, 0))

    def test_any_candidate_gate_fails_the_comparison(self):
        cand = results_for("candidate")
        cand["results"]["oracle-consult/candidate"] = score("oracle-consult/bad-full-scan")
        cmp = ee.compare(results_for("baseline"), cand, thresholds(**REVIEWED))
        self.assertFalse(cmp["pass"])
        self.assertIn("oracle-consult/candidate", cmp["gate_failures"])

    def test_small_n_aggregates_are_directional_and_per_run_bars_decide(self):
        five = ["exact-cve", "exact-arn", "stale-evidence", "permission-denial", "oracle-consult"]
        base, cand = results_for("baseline", five), results_for("candidate", five)
        t = thresholds(**REVIEWED)
        t["aggregate"]["recall_mean_min"] = 1.01  # unreachable: the aggregate misses
        cmp = ee.compare(base, cand, t)
        self.assertEqual(cmp["n"], 5)
        self.assertFalse(cmp["aggregates_enforced"])
        self.assertTrue(cmp["pass"])
        self.assertFalse(next(a for a in cmp["aggregate"] if a["measure"] == "recall mean")["ok"])
        cand["results"]["exact-cve/candidate"] = copy.deepcopy(cand["results"]["exact-cve/candidate"])
        cand["results"]["exact-cve/candidate"]["metrics"]["unsupported_conclusions"] = 2
        self.assertFalse(ee.compare(base, cand, t)["pass"])  # a per-run bar still fails at n=5

    def test_mismatched_case_sets_fail(self):
        base = results_for("baseline", ["exact-cve", "exact-arn"])
        cand = results_for("candidate", ["exact-cve"])
        cmp = ee.compare(base, cand, thresholds(**REVIEWED))
        self.assertFalse(cmp["pass"])
        self.assertTrue(any("not in both runs" in p for p in cmp["problems"]))

    def test_report_names_n_gates_bars_and_carries_no_record_text(self):
        cmp = ee.compare(results_for("baseline"), results_for("candidate"), thresholds(**REVIEWED))
        md = ee.report(cmp)
        self.assertIn("n = 14", md)
        for g in ee.GATES:
            self.assertIn(g, md)
        self.assertIn("context bytes", md)
        self.assertNotIn("libxml2", md)  # no excerpt text from any item


if __name__ == "__main__":
    unittest.main(verbosity=1)
