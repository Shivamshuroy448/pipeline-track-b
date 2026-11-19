# Track B — 15-minute demo script

Interview: Wed Nov 18, 2026, 11:30 PM EST. Prototype link due Tue Nov 17,
11:30 PM EST (24h before). Format: 5 min intro, 15 min demo, 10 min Q&A.
Run `python app.py` before the call and keep the tab open. Default patient
is P002 (James Okafor) — the med-change story.

## 0:00–2:00 — The problem, in one breath

"Patients write like people: 'Threw up twice after dinner, felt nauseous
all morning.' A provider needs that as structured data — symptom, severity,
frequency, timing — stored over weeks, and visible in 30 seconds before
walking into the room. That is what I built: a parser, a store, and a
console. All data is synthetic — four invented oncology patients over six
weeks of chemo and radiation."

Show `schema.sql` (30 seconds): "Raw reports are stored verbatim and never
overwritten. Parsed events live in a separate table with a confidence score
and validation flags. If the parser is wrong, the evidence is still there."

## 2:00–5:00 — The parser and the validation layer

Open `parser.py`. "Deterministic, lexicon plus rules — no API key, runs
offline. Every field traces to the words that produced it."

Demo the three behaviours live (have `python queries.py` output ready, or
run it):
1. **Vague in, flag out.** "Felt bad all day, not great" → an `unparsed`
   event with `needs_review`. "I refused to guess a severity. An invented
   severity in a clinical summary is worse than a missing one."
2. **Conflict caught.** One patient wrote "threw up twice" but answered 0
   in the questionnaire. The parser flags `conflict_q_vs_text` instead of
   picking a side. "A gap of 1 is normal inconsistency — I only flag a gap
   of 2 or more, otherwise the flags table is noise. 13 of 274 events are
   flagged. That is a reviewable number."
3. **Units handled.** One patient weighed in pounds (163 lb). The parser
   converts to 73.9 kg and the trend stays clean.

## 5:00–11:00 — The dashboard (the main act)

Patient P002, default view:
- **Banner:** "Stable · Vomiting this week: 2 · Worst symptom: nausea 9/10
  · Open flags: 2." Say: "That line is the whole point. Thirty seconds."
- **Trend chart:** point at the nausea line (green). "Nausea peaks at 9 in
  week 3. Then this dashed red line — Sep 28, ondansetron switched to
  aprepitant — and nausea falls to 5. The chart tells the story without me."
- **Vomiting bars:** "3, 5, 10, then 4, 1, 2 after the switch. Same story,
  second view."
- Switch to **P004 (David Chen)**: the red alert appears. "Weight alert:
  73.5 kg, down 4.5 kg, 5.8% loss — below the 5% line. The weight chart
  crosses the dashed line in week 6. A provider sees this before the visit,
  not after."
- Scroll to **flags table**: "Every row here is something the parser
  refused to trust silently. Click through to the raw report and judge it
  yourself."
- Scroll to **raw reports**: "And the patient's own words are always one
  scroll down, with the parse next to them."

## 11:00–13:00 — The two queries

Run `python queries.py` (or show the output):
- Q1: vomiting episodes per week. Note the honest label: "Patients report
  twice a week, so this is episodes on reported days, not a 7-day total.
  I would rather under-claim than invent a total."
- Q2: nausea 8.0/10 before the switch, 4.7/10 after. "That is the number
  behind the chart."

## 13:00–15:00 — Trade-offs and AI usage (say these before they ask)

- "Rule-based parser by default — the demo has to run offline, and no
  severity may be hallucinated. The LLM path is built and wired
  (llm_client.py + parse_with_llm, `python build_db.py --llm` with
  GEMINI_API_KEY): it runs behind the same validator, and any failure
  falls back to rule-based, flagged llm_fallback."
- "SQLite, not Postgres — one file, zero setup, right for a prototype.
  The schema ports unchanged."
- "AI wrote the code from my design. I verified it by running the pipeline
  end to end, hand-checking both queries against the data, and
  screenshotting the dashboard for two patients. One real bug I caught
  that way: splitting sentences on every period cut '76.2 kg' into '76'
  and '2 kg'."

## Anticipated Q&A

**Why not just use an LLM for extraction?**
"Both paths exist. The default is rule-based because the demo has to run
offline and every field maps to exact words. The LLM path is wired in —
same prompt contract, same validator, same flags — and a low-confidence
extraction still goes to a human. If the LLM call fails, the rule-based
parser runs instead and the event is flagged llm_fallback."

**How do you handle conflicting reports?**
"Flag, don't resolve. The questionnaire and the free text disagree
sometimes — that is real patient behaviour. The flag goes to a human; the
system never silently picks one."

**What breaks at scale?**
"Three things: the lexicon needs to grow per specialty; the parser is
single-patient, single-threaded; and the flags table needs a real review
workflow instead of a list. The schema already supports all three."

**What about real patient data / HIPAA?**
"Everything here is synthetic and invented. In production this would sit
behind the practice's existing auth and audit logging, and the raw-text
store is exactly what an audit trail needs. I made no compliance claims
beyond that."

**Why is the vomiting chart 'reported days'?**
"Because patients report twice a week. Summing two sampled days and
calling it a weekly total would be inventing data. The honest number is
episodes on reported days, and the chart says so."

**What would you do with another week?**
"Two things: a per-patient 'what changed since last visit' summary —
which is the bridge to Track C — and a real review workflow for the
flags table instead of a list. The LLM path is already done, so the
next step is what a provider does with the output, not how it is
extracted."
