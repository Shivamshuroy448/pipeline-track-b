"""Parser + build tests. Stdlib only, no extra installs.

Run from the project root:
    python -m unittest discover -s tests -v

The integration test locks in the numbers the README and the demo script
quote (52 reports, 274 events, 13 flagged, Q2 8.0 / 4.7, P002 vomiting
10 in week W38). If a parser change moves any of them, this test fails
first, before the demo does.
"""

import os
import sqlite3
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from parser import parse_report, parse_with_llm  # noqa: E402
import build_db  # noqa: E402
from queries import Q2  # noqa: E402


def make_report(text, questionnaire=None):
    return {"report_id": "T001", "patient_id": "P999",
            "reported_at": "2026-09-21T19:30:00",
            "source": "app_free_text", "free_text": text,
            "questionnaire": questionnaire}


def event_for(events, symptom):
    return next(e for e in events if e["symptom"] == symptom)


class TestSeverity(unittest.TestCase):
    def test_numeric_severity(self):
        ev = parse_report(make_report("Throat pain was bad, about 7/10."))
        pain = event_for(ev, "pain")
        self.assertEqual(pain["severity"], 7)
        self.assertEqual(pain["confidence"], 0.9)

    def test_word_severity(self):
        ev = parse_report(make_report("Nausea was severe today."))
        nausea = event_for(ev, "nausea")
        self.assertEqual(nausea["severity"], 8)
        self.assertEqual(nausea["confidence"], 0.75)

    def test_vague_phrase_beats_single_word(self):
        # "felt bad" is a vague phrase, not a severity of 7. The phrase
        # is more specific than the single word inside it, so it wins.
        ev = parse_report(make_report(
            "Nausea felt bad all day, hard to say how bad."))
        nausea = event_for(ev, "nausea")
        self.assertIsNone(nausea["severity"])
        self.assertIn("severity_vague", nausea["validation_flags"])

    def test_mildly_maps_to_two(self):
        # "mildly" is its own lexicon entry (2), not "mild" caught as a
        # substring. The word-boundary rule is what keeps the two apart.
        ev = parse_report(make_report("Feeling mildly nauseous today."))
        nausea = event_for(ev, "nausea")
        self.assertEqual(nausea["severity"], 2)
        self.assertEqual(nausea["confidence"], 0.75)

    def test_badly_is_not_bad(self):
        # Word-boundary matching: "bad" must not fire inside "badly".
        ev = parse_report(make_report("Felt nauseous and slept badly."))
        nausea = event_for(ev, "nausea")
        self.assertIsNone(nausea["severity"])
        self.assertIn("severity_missing", nausea["validation_flags"])

    def test_missing_severity_flagged(self):
        ev = parse_report(make_report(
            "Threw up twice after dinner, felt nauseous all morning."))
        nausea = event_for(ev, "nausea")
        self.assertIsNone(nausea["severity"])
        self.assertIn("severity_missing", nausea["validation_flags"])

    def test_severity_does_not_leak_across_symptoms(self):
        # The 9/10 belongs to pain; nausea in the same report has none.
        ev = parse_report(make_report(
            "Throat pain was about 9/10. Felt nauseous all morning."))
        self.assertEqual(event_for(ev, "pain")["severity"], 9)
        self.assertIsNone(event_for(ev, "nausea")["severity"])


class TestFrequencyAndWeight(unittest.TestCase):
    def test_frequency_estimate(self):
        ev = parse_report(make_report(
            "Threw up a few times today and my mouth hurts."))
        vom = event_for(ev, "vomiting")
        self.assertEqual(vom["frequency_per_day"], 3)
        self.assertIn("frequency_estimate", vom["validation_flags"])

    def test_frequency_does_not_leak_to_pain(self):
        ev = parse_report(make_report(
            "Threw up a few times today and my mouth hurts."))
        pain = event_for(ev, "pain")
        self.assertIsNone(pain["frequency_per_day"])

    def test_pounds_converted_to_kg(self):
        ev = parse_report(make_report(
            "Weighed myself this morning: 163 pounds."))
        w = event_for(ev, "weight")
        self.assertAlmostEqual(w["weight_kg"], 73.9, places=1)

    def test_decimal_weight_not_split(self):
        # Regression test: splitting sentences on every "." once cut
        # "76.2 kg" into "76" / "2 kg" and parsed weight as 2.0 kg.
        ev = parse_report(make_report("Weighed myself: 76.2 kg, down a bit."))
        w = event_for(ev, "weight")
        self.assertEqual(w["weight_kg"], 76.2)


class TestQuestionnaireCrossCheck(unittest.TestCase):
    def test_conflict_gap_two_flagged(self):
        ev = parse_report(make_report("Threw up twice after dinner.",
                                      {"vomiting_episodes": 0}))
        vom = event_for(ev, "vomiting")
        self.assertIn("conflict_q_vs_text", vom["validation_flags"])

    def test_conflict_gap_one_not_flagged(self):
        # A gap of 1 is normal patient inconsistency, not a conflict.
        ev = parse_report(make_report("Threw up twice after dinner.",
                                      {"vomiting_episodes": 1}))
        vom = event_for(ev, "vomiting")
        self.assertNotIn("conflict_q_vs_text", vom["validation_flags"])

    def test_questionnaire_only_report(self):
        ev = parse_report(make_report(None, {"nausea": 6, "pain": 4,
                                             "vomiting_episodes": 2,
                                             "weight_kg": 70.0}))
        by_symptom = {e["symptom"]: e for e in ev}
        self.assertEqual(by_symptom["nausea"]["severity"], 6)
        self.assertEqual(by_symptom["vomiting"]["frequency_per_day"], 2)
        self.assertEqual(by_symptom["weight"]["weight_kg"], 70.0)
        self.assertEqual(by_symptom["nausea"]["validation_flags"],
                         "questionnaire_only")

    def test_unparsed_fallback(self):
        ev = parse_report(make_report(
            "Felt bad all day, not great. Hard to say how bad."))
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["symptom"], "unparsed")
        self.assertIn("needs_review", ev[0]["validation_flags"])


class TestBuildIntegration(unittest.TestCase):
    def test_verified_counts_and_queries(self):
        # Numbers the README and the demo script quote. A parser change
        # that moves any of them fails here before it reaches the demo.
        old_cwd = os.getcwd()
        try:
            os.chdir(PROJECT_ROOT)
            with tempfile.TemporaryDirectory() as tmp:
                db = os.path.join(tmp, "t.db")
                build_db.build(db_path=db, data_path="data/reports.json")
                conn = sqlite3.connect(db)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM reports")
                    .fetchone()[0], 52)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM symptom_events")
                    .fetchone()[0], 274)
                flagged = conn.execute(
                    "SELECT COUNT(*) FROM symptom_events "
                    "WHERE validation_flags != '' "
                    "AND validation_flags != 'questionnaire_only'"
                ).fetchone()[0]
                self.assertEqual(flagged, 13)
                before, after = conn.execute(Q2).fetchone()
                self.assertEqual((before, after), (8.0, 4.7))
                w38 = conn.execute(
                    "SELECT COALESCE(SUM(e.frequency_per_day), 0) "
                    "FROM reports r JOIN symptom_events e "
                    "ON e.report_id = r.report_id "
                    "WHERE e.patient_id = 'P002' AND e.symptom = 'vomiting' "
                    "AND strftime('%Y-W%W', r.reported_at) = '2026-W38'"
                ).fetchone()[0]
                self.assertEqual(w38, 10)
                conn.close()
        finally:
            os.chdir(old_cwd)


class TestLLMPath(unittest.TestCase):
    def test_llm_events_go_through_validator(self):
        # The LLM proposes; _validate_event disposes. A severity the
        # LLM reports gets confidence 0.8; a missing one is flagged,
        # never guessed.
        def fake_llm(text):
            return [
                {"symptom": "vomiting", "severity": None,
                 "frequency_per_day": 2, "timing": "after dinner",
                 "related_medication": None},
                {"symptom": "nausea", "severity": None,
                 "frequency_per_day": None, "timing": "all morning",
                 "related_medication": None},
            ]
        ev = parse_with_llm(make_report(
            "Threw up twice after dinner, felt nauseous all morning."),
            fake_llm)
        vom = event_for(ev, "vomiting")
        self.assertEqual(vom["frequency_per_day"], 2)
        self.assertEqual(vom["confidence"], 0.85)
        nausea = event_for(ev, "nausea")
        self.assertIsNone(nausea["severity"])
        self.assertIn("severity_missing", nausea["validation_flags"])

    def test_llm_conflict_flagged_and_scored(self):
        # LLM says nausea 9, questionnaire says 3: gap of 6, so the
        # conflict flag fires and confidence drops 0.8 - 0.25 = 0.55.
        def fake_llm(text):
            return [{"symptom": "nausea", "severity": 9,
                     "frequency_per_day": None, "timing": None,
                     "related_medication": None}]
        ev = parse_with_llm(make_report("Nausea was terrible today.",
                                        {"nausea": 3}), fake_llm)
        nausea = event_for(ev, "nausea")
        self.assertIn("conflict_q_vs_text", nausea["validation_flags"])
        self.assertEqual(nausea["confidence"], 0.55)

    def test_llm_bad_values_dropped_not_stored(self):
        # Unknown symptom dropped; severity 15 becomes None, not a
        # stored 15/10; frequency on a non-vomiting symptom is ignored.
        def fake_llm(text):
            return [
                {"symptom": "headache", "severity": 5,
                 "frequency_per_day": None, "timing": None,
                 "related_medication": None},
                {"symptom": "nausea", "severity": 15,
                 "frequency_per_day": 7, "timing": None,
                 "related_medication": None},
            ]
        ev = parse_with_llm(make_report("Nausea was severe today."),
                            fake_llm)
        self.assertEqual([e["symptom"] for e in ev], ["nausea"])
        nausea = ev[0]
        self.assertIsNone(nausea["severity"])
        self.assertIsNone(nausea["frequency_per_day"])

    def test_llm_failure_falls_back_and_flags(self):
        # A dead API must not kill the demo: rule-based runs instead,
        # and every event says so.
        def broken_llm(text):
            raise RuntimeError("boom")
        ev = parse_with_llm(make_report(
            "Threw up twice after dinner, felt nauseous all morning."),
            broken_llm)
        self.assertTrue(ev)
        for e in ev:
            self.assertIn("llm_fallback", e["validation_flags"])
        self.assertEqual(event_for(ev, "vomiting")["frequency_per_day"], 2)

    def test_llm_empty_result_falls_back(self):
        ev = parse_with_llm(make_report("Threw up twice after dinner."),
                            lambda text: [])
        self.assertIn("llm_fallback",
                      event_for(ev, "vomiting")["validation_flags"])

    def test_gemini_client_needs_key_and_prompt_is_strict(self):
        # No network in this test: without a key it must fail fast with
        # a plain message, and the prompt must carry the rules.
        # Hermetic: the test must pass even when GEMINI_API_KEY is set
        # in the environment (e.g. a live-test run), so drop it first.
        import llm_client
        import os
        saved = os.environ.pop("GEMINI_API_KEY", None)
        try:
            self.assertRaises(RuntimeError, llm_client.gemini_extract,
                              "Threw up twice.")
        finally:
            if saved is not None:
                os.environ["GEMINI_API_KEY"] = saved
        prompt = llm_client.build_prompt("Threw up twice after dinner.")
        self.assertIn("NEVER guess a severity", prompt)
        self.assertIn("vomiting", prompt)
        self.assertIn("Threw up twice after dinner.", prompt)

    def test_llm_build_end_to_end_with_fake(self):
        # The --llm build path works with any llm_call, not just Gemini:
        # build the whole DB through the LLM path and check the shape.
        def fake_llm(text):
            return parse_report(make_report(text))
        old_cwd = os.getcwd()
        try:
            os.chdir(PROJECT_ROOT)
            with tempfile.TemporaryDirectory() as tmp:
                db = os.path.join(tmp, "llm.db")
                build_db.build(db_path=db, data_path="data/reports.json",
                               parse_fn=lambda r: parse_with_llm(r, fake_llm))
                conn = sqlite3.connect(db)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM reports")
                    .fetchone()[0], 52)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM symptom_events")
                    .fetchone()[0], 274)
                conn.close()
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
