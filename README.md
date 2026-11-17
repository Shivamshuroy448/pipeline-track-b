# Dr.Tracker — Track B: Patient-Reported Data, Store, Manage & Chart

Prototype for the Pipeline Securities Data Intelligence Engineering Intern
assessment. Scenario: head & neck radiation + chemotherapy (the oncology
demo). **All data is synthetic — invented patients, invented reports. No
real patient information anywhere.**

## Run it

```bash
pip install -r requirements.txt
python generate_data.py   # writes data/reports.json (seeded, deterministic)
python build_db.py        # parses every report into tracker.db (SQLite)
python queries.py         # the two required queries + the flags list
python -m unittest discover -s tests -v   # 16 tests: parser + verified numbers
python app.py             # dashboard at http://127.0.0.1:8050
```

`app.py` builds the database itself if `tracker.db` is missing, so
`python app.py` alone is enough for the demo.

## What is in here

| File | What it does |
|---|---|
| `generate_data.py` | Seeded generator: 4 patients, 6 weeks, 2 reports/week (Mon + Thu), free text and/or questionnaire. Includes 4 hand-written edge cases (vague report, text-vs-questionnaire conflict, "a few times", weight in pounds). |
| `schema.sql` | SQLite schema. Raw reports are stored verbatim and never overwritten; parsed symptom events live in a separate table with confidence + validation flags. |
| `parser.py` | Deterministic lexicon + rules parser: symptom, severity 0–10, frequency, timing, medication. No API key, runs offline. An LLM slot exists (`parse_with_llm`) but is intentionally not the default. |
| `build_db.py` | Loads the data, parses every report, writes `tracker.db`. |
| `queries.py` | Q1 vomiting episodes/week; Q2 nausea 7 days before vs after the P002 antiemetic switch (ondansetron → aprepitant, 2026-09-28); Q3 validation flags. |
| `tests/test_parser.py` | 16 tests (stdlib `unittest`, nothing to install): severity, vague phrases, word boundaries, frequency, pounds-to-kg, the decimal-weight regression, questionnaire cross-checks, and an integration test that locks in the verified numbers below. |
| `app.py` | Dash provider console: patient picker, 30-second status banner, alerts, severity trends with a med-change marker, vomiting/week bars, weight trend with a 5% alert line, flags table, raw reports with their parses. |
| `DEMO_SCRIPT.md` | 15-minute talk track + anticipated Q&A. |

## Design decisions (the ones to defend in the interview)

1. **Raw text is never overwritten.** The `reports` table keeps the exact
   words; `symptom_events` is a derived view. Any parse can be audited or
   re-run. If the parser is wrong, the evidence is still there.
2. **Vague reports produce a flag, never a guessed number.** "Felt bad all
   day" becomes an `unparsed` event with `needs_review`, not a severity 5.
   An invented severity in a clinical summary is worse than a missing one.
   The same rule applies inside the severity lookup: a vague phrase
   ("felt bad") takes precedence over the single word inside it ("bad"),
   and severity words match on word boundaries, so "bad" never fires
   inside "badly".
3. **Confidence is explicit and per-event.** Numeric severity (7/10) scores
   0.9; severity words 0.75; vague 0.4. Vomiting is scored on its count
   (the count *is* the measurement); weight on the measured value.
4. **Validation, not blind trust.** Text and questionnaire are cross-checked:
   a gap of 2+ in vomiting count, or 4+ in severity, raises
   `conflict_q_vs_text`. A gap of 1 is normal patient inconsistency and is
   deliberately *not* flagged. 13 of 274 events are flagged — a reviewable
   number, not noise.
5. **The dashboard answers the 30-second question first.** Status banner
   (Worsening / Stable / Improving), active alerts (weight below the 5%
   line, vomiting spike), then trends. Raw text is one scroll down, not in
   the way.
6. **Frequency is only extracted for vomiting.** "Threw up a few times and
   my mouth hurts" — the "few times" belongs to vomiting, not to pain.
   The parser works sentence-by-sentence so a cue cannot leak across
   symptoms. (A real bug found during testing: splitting sentences on every
   period cut "76.2 kg" into "76" and "2 kg". Fixed by splitting on
   punctuation + whitespace.)
7. **"Episodes per week" is labelled honestly.** Patients report twice a
   week, so the bar chart sums episodes on *reported* days — it is not a
   7-day total, and the chart says so.

## Trade-offs (say these out loud — they are strengths)

- **Rule-based parser instead of an LLM by default.** The demo must run
  offline, and every extraction must be traceable to the words that
  produced it. An LLM extraction step with structured output would slot
  into `parse_with_llm` behind the *same* validator — the LLM proposes,
  the validator disposes.
- **SQLite, not Postgres.** One file, zero setup, correct for a prototype.
  The schema ports unchanged.
- **Synthetic data, seeded.** Realistic trajectories (side effects build
  weeks 2–4, P002 improves after the drug switch, P004 loses 5.8% of body
  weight) but fully invented. No privacy risk, reproducible on demand.
- **One dashboard, not a full EHR.** Track B is the storage + charting
  layer; delivery into an EHR is Track C and is out of scope here.

## AI usage (the brief asks for this explicitly)

- AI (Muse) wrote the code, the generator, and this README from my design
  decisions. I checked its output by: running the full pipeline end to
  end; verifying the two queries by hand against the generated data;
  screenshotting the dashboard for two patients and reading every number
  on it; and deliberately testing edge cases (vague text, conflicting
  counts, pounds-vs-kg, decimal splitting).
- I chose *not* to rely on AI where it would have hurt: the parser is
  rule-based, not LLM-based, so no severity is ever hallucinated; and no
  number on the dashboard is AI-generated — every value traces to a row
  in `tracker.db`, which traces to a line in `data/reports.json`.

## Verified numbers (from `python queries.py` + dashboard screenshots, 2026-11-17)

- 52 reports, 274 symptom events, 13 flagged for review.
- P002 vomiting: 3 → 5 → **10** (week of Sep 21) → 4 → 1 → 2 episodes/week
  after the Sep 28 antiemetic switch.
- P002 nausea: **8.0/10** in the 7 days before the switch, **4.7/10** in
  the 7 days after.
- P004 weight: 78.0 → 73.5 kg (−5.8%), crossing the 5% alert line
  (74.1 kg) in week 6 (between Oct 8 and Oct 12).
- Dashboard banner, P002: "Stable · Vomiting this week: 2 · Worst symptom:
  nausea 9/10 · Open flags: 2". P004: "Stable · Vomiting this week: 0 ·
  Worst symptom: swallowing 9/10 · Open flags: 2", with the weight alert
  showing.
