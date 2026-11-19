"""
Free-text -> structured symptom parser (deterministic, no API key needed).

Design decisions (defended in README.md):
- Lexicon + rules, not a black box. Every extracted field can be traced to
  the exact words that produced it, which is what makes validation possible.
- Two extraction paths, one validator. The default is rule-based: the
  demo must run offline, and a hallucinated severity in a clinical
  summary is worse than a missing one. parse_with_llm wires a real LLM
  (see llm_client.py) behind the SAME validator (_validate_event):
  the LLM proposes, the validator disposes. If the LLM call fails or
  returns nothing usable, the rule-based parser runs instead and every
  event is flagged llm_fallback, so the fallback is visible.
- Nothing is silently dropped. A vague report produces an event with
  severity NULL and a flag, never a guessed number.
- Confidence is explicit and every event carries validation flags.

Validation flags:
  severity_missing   no severity cue in the text at all
  severity_vague     only a weak cue ("felt bad", "not great")
  frequency_estimate "a few times" -> recorded as 3, flagged as an estimate
  conflict_q_vs_text questionnaire disagrees with the free text
  needs_review       confidence < 0.5, a human should look at it
  llm_fallback       LLM call failed or returned nothing usable; the
                     rule-based parser ran instead (LLM path only)
"""

import re
from datetime import datetime, timezone

SEVERITY_WORDS = {
    "very mild": 1, "a little": 2, "mild": 3, "mildly": 2, "moderate": 5,
    "quite bad": 6, "bad": 7, "severe": 8, "very severe": 9,
    "terrible": 8, "the worst": 9, "worst": 9, "awful": 8,
    "exhausted": 7,
}
VAGUE_WORDS = ["felt bad", "not great", "not good", "hard to say",
               "felt off", "rough day", "not feeling well"]
FREQUENCY_WORDS = {
    "once": 1, "twice": 2, "three times": 3, "four times": 4,
    "five times": 5, "six times": 6, "a few times": 3, "several times": 3,
}
TIMING_WORDS = ["after dinner", "after eating", "after chemo",
                "in the morning", "all morning", "all day", "at night",
                "in the evening", "after lunch", "after breakfast"]
MEDICATIONS = ["ondansetron", "aprepitant", "cisplatin", "carboplatin",
               "morphine", "magic mouthwash", "mouthwash"]

# symptom -> trigger phrases (checked longest-first, word-boundary safe)
SYMPTOMS = {
    "nausea": [r"nauseous", r"nausea", r"queasy", r"sick to (my |the )?stomach"],
    "vomiting": [r"threw up", r"vomited", r"vomiting", r"throwing up",
                 r"throw up"],
    "mouth_sores": [r"mouth sores", r"sores in my mouth", r"mouth sore",
                    r"mouth ulcer", r"ulcer"],
    "pain": [r"throat pain", r"\bpain\b", r"\bhurts\b", r"aching",
             r"sore throat"],
    "swallowing": [r"hard to swallow", r"trouble swallowing",
                   r"can'?t swallow", r"swallowing", r"food gets stuck"],
    "fatigue": [r"exhausted", r"very tired", r"low energy", r"fatigue",
                r"barely got out of bed"],
    "weight": [r"weighed myself", r"lost (some )?weight", r"lost \d+",
               r"\d+\s*(pounds|lbs|kg)"],
}


def _find_severity(text):
    """Return (severity 0-10 or None, how it was found)."""
    m = re.search(r"(\d{1,2})\s*/\s*10", text)
    if m:
        return max(0, min(10, int(m.group(1)))), "numeric"
    m = re.search(r"(\d{1,2})\s+out of 10", text)
    if m:
        return max(0, min(10, int(m.group(1)))), "numeric"
    # Vague phrases first: "felt bad" is a vague phrase, not a severity
    # of 7. The phrase is more specific than the single word inside it,
    # so it wins over the severity-word list below.
    for phrase in sorted(VAGUE_WORDS, key=len, reverse=True):
        if phrase in text:
            return None, "vague"
    for phrase, value in sorted(SEVERITY_WORDS.items(),
                                key=lambda kv: -len(kv[0])):
        # Word boundaries: "mild" must not fire inside "mildly".
        if re.search(r"\b" + re.escape(phrase) + r"\b", text):
            return value, "word"
    return None, "missing"


def _find_frequency(text):
    for phrase, value in sorted(FREQUENCY_WORDS.items(),
                                key=lambda kv: -len(kv[0])):
        if phrase in text:
            estimated = phrase in ("a few times", "several times")
            return value, estimated
    m = re.search(r"(\d+)\s+times", text)
    if m:
        return int(m.group(1)), False
    return None, False


def _find_timing(text):
    for phrase in TIMING_WORDS:
        if phrase in text:
            return phrase
    return None


def _find_medication(text):
    for med in MEDICATIONS:
        if med in text:
            return med
    return None


def _coerce_int(value, low, high):
    """Strict int coercion for LLM output: bad values become None."""
    if isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < low or n > high:
        return None
    return n


def _coerce_float(value):
    """Strict float coercion for LLM output: bad values become None."""
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n <= 0 or n >= 500:
        return None
    return n


def _validate_event(symptom, severity, how, frequency, estimated, q,
                    weight_measured=False):
    """Shared validator for both parser paths: rule-based and LLM.

    Returns (confidence, flags). The rules:
    - severity missing/vague is flagged, never guessed (not for vomiting
      or weight, which have no severity scale);
    - "a few times" is an estimate, flagged as one;
    - text vs questionnaire: a gap of 4+ in severity or 2+ in vomiting
      count is a conflict; a gap of 1 is normal inconsistency;
    - confidence: explicit numbers 0.9, LLM-reported severity 0.8,
      severity words 0.75, vague 0.4, missing 0.5; vomiting is scored
      on its count, weight on the measured value; a conflict costs 0.25;
    - confidence below 0.5 means a human should review.
    """
    flags = []
    if symptom not in ("vomiting", "weight"):
        if how == "missing":
            flags.append("severity_missing")
        elif how == "vague":
            flags.append("severity_vague")
    if estimated:
        flags.append("frequency_estimate")
    if q:
        q_map = {"nausea": q.get("nausea"), "pain": q.get("pain"),
                 "mouth_sores": q.get("mouth_sores"),
                 "swallowing": q.get("swallowing")}
        if symptom in q_map and q_map[symptom] is not None \
                and severity is not None:
            if abs(q_map[symptom] - severity) >= 4:
                flags.append("conflict_q_vs_text")
        if symptom == "vomiting" and q.get("vomiting_episodes") is not None \
                and frequency is not None:
            if abs(q["vomiting_episodes"] - frequency) >= 2:
                flags.append("conflict_q_vs_text")
    if symptom == "vomiting":
        confidence = 0.85 if (frequency is not None and not estimated) \
            else (0.6 if estimated else 0.5)
    elif symptom == "weight":
        confidence = 0.9 if (weight_measured
                             or q.get("weight_kg") is not None) else 0.5
    else:
        confidence = {"numeric": 0.9, "llm": 0.8, "word": 0.75,
                      "vague": 0.4, "missing": 0.5}[how]
        if frequency is not None:
            confidence += 0.05
    if "conflict_q_vs_text" in flags:
        confidence -= 0.25
    confidence = max(0.1, min(0.95, confidence))
    if confidence < 0.5:
        flags.append("needs_review")
    return round(confidence, 2), flags


def parse_report(report):
    """Parse one report dict into a list of symptom-event dicts."""
    text = (report.get("free_text") or "").lower()
    q = report.get("questionnaire") or {}
    events = []
    now = datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")

    if not text.strip():
        # Questionnaire-only report: carry the numbers through as events
        # with full confidence on the number itself, flagged as structured.
        mapping = {"nausea": q.get("nausea"),
                   "pain": q.get("pain"), "mouth_sores": q.get("mouth_sores"),
                   "swallowing": q.get("swallowing")}
        for symptom, severity in mapping.items():
            if severity is None:
                continue
            events.append({
                "symptom": symptom, "severity": int(severity),
                "frequency_per_day": None, "timing": None,
                "related_medication": None, "confidence": 0.95,
                "validation_flags": "questionnaire_only",
            })
        # Vomiting has no severity scale — its number IS the frequency.
        if q.get("vomiting_episodes") is not None:
            events.append({
                "symptom": "vomiting", "severity": None,
                "frequency_per_day": int(q["vomiting_episodes"]),
                "timing": None, "related_medication": None,
                "confidence": 0.95,
                "validation_flags": "questionnaire_only",
            })
        if q.get("weight_kg") is not None:
            events.append({
                "symptom": "weight", "severity": None,
                "frequency_per_day": None, "timing": None,
                "related_medication": None, "confidence": 0.95,
                "validation_flags": "questionnaire_only",
                "weight_kg": q["weight_kg"],
            })
        return events

    for symptom, patterns in SYMPTOMS.items():
        # Work on the sentence(s) mentioning this symptom, so a severity
        # written about pain does not leak onto nausea.
        # Split on sentence-ending punctuation followed by whitespace —
        # NOT on every period, or decimals like "76.2 kg" get cut in half
        # ("76" / "2 kg") and the weight parser reads 2.0 kg.
        sentences = [s for s in re.split(r"[.!;]\s+", text) if s.strip()]
        hits = [s for s in sentences
                if any(re.search(p, s) for p in patterns)]
        if not hits:
            continue
        snippet = " ".join(hits)
        severity, how = _find_severity(snippet)
        # Frequency is only meaningful for vomiting in this dataset: a
        # "few times" written about vomiting must not leak onto pain in
        # the same sentence. Vomiting and weight have no severity scale,
        # so a missing severity is not a flag for them.
        if symptom == "vomiting":
            frequency, estimated = _find_frequency(snippet)
        else:
            frequency, estimated = None, False
        # Same validator the LLM path uses: the extraction proposes,
        # _validate_event disposes.
        weight_measured = (
            re.search(r"(\d+(?:\.\d+)?)\s*(pounds|lbs|kg)", snippet)
            is not None) if symptom == "weight" else False
        confidence, flags = _validate_event(
            symptom, severity, how, frequency, estimated, q,
            weight_measured=weight_measured)

        event = {
            "symptom": symptom,
            "severity": severity,
            "frequency_per_day": frequency,
            "timing": _find_timing(snippet),
            "related_medication": _find_medication(snippet),
            "confidence": round(confidence, 2),
            "validation_flags": ",".join(flags),
        }
        # Weight: keep the measured value on the event for the chart.
        if symptom == "weight":
            m = re.search(r"(\d+(?:\.\d+)?)\s*(pounds|lbs|kg)", snippet)
            if m:
                value = float(m.group(1))
                if m.group(2) in ("pounds", "lbs"):
                    value = round(value * 0.453592, 1)
                event["weight_kg"] = value
            elif q.get("weight_kg") is not None:
                event["weight_kg"] = q["weight_kg"]
        events.append(event)

    # Weight from the questionnaire is a measurement, not a parse: record
    # it whenever it exists and the text did not already produce a weight
    # event, so the weight trend has a point for every reporting day.
    if q.get("weight_kg") is not None and not any(
            e["symptom"] == "weight" for e in events):
        events.append({
            "symptom": "weight", "severity": None,
            "frequency_per_day": None, "timing": None,
            "related_medication": None, "confidence": 0.95,
            "validation_flags": "questionnaire_only",
            "weight_kg": q["weight_kg"],
        })

    # No symptom matched at all: record that explicitly, don't drop the row.
    if not events:
        events.append({
            "symptom": "unparsed", "severity": None,
            "frequency_per_day": None, "timing": None,
            "related_medication": None, "confidence": 0.1,
            "validation_flags": "severity_missing,needs_review",
        })
    for e in events:
        e["extracted_at"] = now
    return events


def _flag_fallback(events):
    """Mark every event as a rule-based fallback after an LLM failure."""
    for e in events:
        flags = e.get("validation_flags", "")
        e["validation_flags"] = (
            (flags + ",llm_fallback") if flags else "llm_fallback")
    return events


def parse_with_llm(report, llm_call):
    """LLM extraction path: same output contract, same validator.

    llm_call(text) must return a list of dicts, one per symptom found,
    with keys symptom, severity, frequency_per_day, timing,
    related_medication (and weight_kg for weight events). Severity may be
    None when the text does not state one — the LLM must never guess.
    Every returned event is normalised, then run through _validate_event,
    exactly like the rule-based path: the LLM proposes, the validator
    disposes. Unknown symptoms and out-of-range numbers are dropped,
    never stored.

    If the LLM call fails or returns nothing usable, the rule-based
    parser runs instead and every event is flagged llm_fallback, so the
    demo never dies on a bad API response and the fallback is visible.
    Not used by default; the demo runs fully offline without it.
    """
    text = (report.get("free_text") or "").strip()
    q = report.get("questionnaire") or {}
    now = datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    if not text:
        return parse_report(report)
    try:
        raw = llm_call(text)
    except Exception:
        return _flag_fallback(parse_report(report))
    if not isinstance(raw, list) or not raw:
        return _flag_fallback(parse_report(report))
    events = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        symptom = str(item.get("symptom") or "").strip().lower()
        if symptom not in SYMPTOMS:
            continue
        severity = _coerce_int(item.get("severity"), 0, 10)
        frequency = _coerce_int(item.get("frequency_per_day"), 0, 99) \
            if symptom == "vomiting" else None
        timing = item.get("timing") or None
        timing = str(timing).strip().lower() if timing else None
        med = item.get("related_medication") or None
        med = str(med).strip().lower() if med else None
        weight_kg = None
        if symptom == "weight":
            weight_kg = _coerce_float(item.get("weight_kg"))
        how = "llm" if severity is not None else "missing"
        confidence, flags = _validate_event(
            symptom, severity, how, frequency, False, q,
            weight_measured=(weight_kg is not None))
        event = {
            "symptom": symptom, "severity": severity,
            "frequency_per_day": frequency, "timing": timing,
            "related_medication": med, "confidence": confidence,
            "validation_flags": ",".join(flags),
        }
        if weight_kg is not None:
            event["weight_kg"] = weight_kg
        events.append(event)
    if not events:
        return _flag_fallback(parse_report(report))
    # Weight from the questionnaire still gets a point for every
    # reporting day, same as the rule-based path.
    if q.get("weight_kg") is not None and not any(
            e["symptom"] == "weight" for e in events):
        events.append({
            "symptom": "weight", "severity": None,
            "frequency_per_day": None, "timing": None,
            "related_medication": None, "confidence": 0.95,
            "validation_flags": "questionnaire_only",
            "weight_kg": q["weight_kg"],
        })
    for e in events:
        e["extracted_at"] = now
    return events
