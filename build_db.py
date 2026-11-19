"""
Build the SQLite store from data/reports.json.

  python build_db.py        ->  writes tracker.db (deletes any old one)
  python build_db.py --llm  ->  same, but extraction goes through the LLM
                                 (needs GEMINI_API_KEY; see llm_client.py).
                                 Every LLM event runs through the same
                                 validator as the rule-based path, and any
                                 LLM failure falls back to rule-based with
                                 an llm_fallback flag.

Steps: create schema -> load patients, medications, medication changes ->
store every raw report verbatim -> parse each report -> store events.
The raw text is never overwritten, so any parse can be audited or re-run.
"""

import argparse
import json
import os
import sqlite3

from parser import parse_report, parse_with_llm

DB_PATH = "tracker.db"


def build(db_path=DB_PATH, data_path="data/reports.json", use_llm=False,
          parse_fn=None):
    if parse_fn is None:
        if use_llm:
            from llm_client import gemini_extract
            parse_fn = lambda r: parse_with_llm(r, gemini_extract)
            print("LLM extraction path (Gemini); rule-based fallback "
                  "on errors, flagged llm_fallback.")
        else:
            parse_fn = parse_report
    if os.path.exists(db_path):
        os.remove(db_path)
    with open(data_path) as f:
        data = json.load(f)

    conn = sqlite3.connect(db_path)
    with open("schema.sql") as f:
        conn.executescript(f.read())

    for p in data["patients"]:
        conn.execute(
            "INSERT INTO patients VALUES (?,?,?,?,?,?,?,?,?)",
            (p["patient_id"], p["name"], p["age"], p["sex"], p["diagnosis"],
             p["treatment"], p["start_date"], p["weight_start_kg"],
             p["weight_alert_kg"]))
    for m in data["medications"]:
        conn.execute(
            "INSERT INTO medications (patient_id, name, purpose, start_date,"
            " end_date) VALUES (?,?,?,?,?)",
            (m["patient_id"], m["name"], m["purpose"], m["start_date"],
             m["end_date"]))
    for c in data["medication_changes"]:
        conn.execute(
            "INSERT INTO medication_changes (patient_id, old_med, new_med,"
            " change_date, reason) VALUES (?,?,?,?,?)",
            (c["patient_id"], c["old_med"], c["new_med"], c["change_date"],
             c["reason"]))

    n_events = 0
    n_flagged = 0
    for r in data["reports"]:
        q = r.get("questionnaire") or {}
        conn.execute(
            "INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (r["report_id"], r["patient_id"], r["reported_at"], r["source"],
             r.get("free_text"), q.get("nausea"), q.get("vomiting_episodes"),
             q.get("pain"), q.get("mouth_sores"), q.get("swallowing"),
             q.get("weight_kg")))
        for e in parse_fn(r):
            flags = e.get("validation_flags", "")
            if flags and flags != "questionnaire_only":
                n_flagged += 1
            conn.execute(
                "INSERT INTO symptom_events (report_id, patient_id, symptom,"
                " severity, frequency_per_day, timing, related_medication,"
                " confidence, validation_flags, weight_kg, extracted_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (r["report_id"], r["patient_id"], e["symptom"],
                 e.get("severity"), e.get("frequency_per_day"),
                 e.get("timing"), e.get("related_medication"),
                 e.get("confidence"), flags, e.get("weight_kg"),
                 e.get("extracted_at")))
            n_events += 1

    conn.commit()
    counts = conn.execute(
        "SELECT COUNT(*) FROM reports").fetchone()[0]
    conn.close()
    print(f"built {db_path}: {counts} reports, {n_events} symptom events, "
          f"{n_flagged} flagged for review")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true",
                    help="extract with the LLM (needs GEMINI_API_KEY)")
    args = ap.parse_args()
    build(use_llm=args.llm)
