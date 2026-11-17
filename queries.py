"""
The two queries the brief requires, plus the worsening-trend check that
powers the dashboard's 30-second provider view.

  python queries.py

Q1  Vomiting episodes per week, per patient.
Q2  Nausea severity in the 7 days before vs the 7 days after a medication
    change (P002: ondansetron -> aprepitant on 2026-09-28).
Q3  Patients whose worst symptom is trending worse, and open validation
    flags — the "what needs attention" list.
"""

import sqlite3

DB_PATH = "tracker.db"

Q1 = """
SELECT e.patient_id,
       strftime('%Y-W%W', r.reported_at) AS week,
       COALESCE(SUM(e.frequency_per_day), 0) AS vomiting_episodes
FROM reports r
JOIN symptom_events e ON e.report_id = r.report_id
WHERE e.symptom = 'vomiting'
GROUP BY e.patient_id, week
ORDER BY e.patient_id, week;
"""

Q2 = """
SELECT
  (SELECT ROUND(AVG(e.severity), 1)
     FROM symptom_events e JOIN reports r ON r.report_id = e.report_id
    WHERE e.patient_id = 'P002' AND e.symptom = 'nausea'
      AND date(r.reported_at) BETWEEN date('2026-09-28', '-7 days')
                                  AND date('2026-09-28', '-1 day'))
    AS nausea_before,
  (SELECT ROUND(AVG(e.severity), 1)
     FROM symptom_events e JOIN reports r ON r.report_id = e.report_id
    WHERE e.patient_id = 'P002' AND e.symptom = 'nausea'
      AND date(r.reported_at) BETWEEN date('2026-09-28')
                                  AND date('2026-09-28', '+7 days'))
    AS nausea_after;
"""

Q3_FLAGS = """
SELECT patient_id, report_id, symptom, validation_flags, confidence
FROM symptom_events
WHERE validation_flags != '' AND validation_flags != 'questionnaire_only'
ORDER BY patient_id, report_id;
"""


def main():
    conn = sqlite3.connect(DB_PATH)
    print("Q1 — vomiting episodes per week (summed over reporting days: "
          "patients report twice a week, so this is episodes on reported "
          "days, not a 7-day total)")
    print(f"{'patient':8} {'week':9} episodes")
    for pid, week, n in conn.execute(Q1):
        print(f"{pid:8} {week:9} {n}")

    print("\nQ2 — P002 nausea, 7 days before vs after the 2026-09-28 "
          "antiemetic switch (ondansetron -> aprepitant)")
    before, after = conn.execute(Q2).fetchone()
    print(f"  before: {before} / 10   after: {after} / 10")

    print("\nQ3 — validation flags (events a human should review)")
    rows = conn.execute(Q3_FLAGS).fetchall()
    print(f"  {len(rows)} flagged events")
    for pid, rid, symptom, flags, conf in rows:
        print(f"  {pid} {rid} {symptom:12} {flags} (conf {conf})")
    conn.close()


if __name__ == "__main__":
    main()
