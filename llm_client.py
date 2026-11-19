"""LLM extraction client for the Track B prototype (optional path).

Default extraction is the rule-based parser in parser.py, which runs
offline. This module wires a real LLM behind the same validator:
`gemini_extract(text)` returns the list of event dicts that
`parser.parse_with_llm` expects, and parse_with_llm runs every one of
them through _validate_event. The LLM proposes, the validator disposes.

Needs GEMINI_API_KEY in the environment. Never hardcode a key, never
commit one, never print one. No new dependencies: stdlib urllib only.

    GEMINI_API_KEY=... python build_db.py --llm

The key is only needed for the --llm build. Everything else — tests,
the default build, the dashboard — runs without it.
"""

import json
import os
import urllib.error
import urllib.request

ALLOWED_SYMPTOMS = ["nausea", "vomiting", "mouth_sores", "pain",
                    "swallowing", "fatigue", "weight"]
KNOWN_MEDICATIONS = ["ondansetron", "aprepitant", "cisplatin",
                     "carboplatin", "morphine", "magic mouthwash",
                     "mouthwash"]

PROMPT_TEMPLATE = """You extract structured symptom data from a patient-reported
health update. The patient is in chemotherapy. Read the report below and
return a JSON array, one object per symptom you find. No other text.

Rules:
- symptom must be exactly one of: {symptoms}.
- severity is an integer 0-10, or null when the text does not state one.
  NEVER guess a severity. "Felt bad", "not great", "hard to say" mean
  null, not a number. But DO map severity words to numbers when the
  text uses them: very mild 1, a little 2, mildly 2, mild 3, moderate
  5, quite bad 6, bad 7, severe 8, terrible 8, awful 8, very severe 9,
  worst 9. Only use null when the text gives no severity cue at all,
  not when it describes severity in words.
- frequency_per_day is an integer only for vomiting (how many times the
  patient threw up). For every other symptom it must be null.
- timing is a short phrase from the text such as "after dinner" or
  "all morning", or null when not stated.
- related_medication is a medication named in the text (for example
  {meds}), or null when none is named.
- weight_kg is a number (kilograms) only for the weight symptom, or
  null. Convert pounds to kg (1 lb = 0.453592 kg).
- If the report mentions no symptom at all, return an empty array [].

Report:
{text}

Return ONLY the JSON array."""


def build_prompt(text):
    """The exact prompt sent to the model (unit-testable, no network)."""
    return PROMPT_TEMPLATE.format(
        symptoms=", ".join(ALLOWED_SYMPTOMS),
        meds=", ".join(KNOWN_MEDICATIONS),
        text=text)


def gemini_extract(text, model=None, api_key=None, timeout=30):
    """Call Gemini and return the extracted event list.

    Default model is gemini-3.5-flash-lite: it is the 3.5 Flash model
    that answers on this key. Override with the GEMINI_MODEL env var
    or the model argument. (gemini-2.0-flash was retired June 1, 2026;
    gemini-3.6-flash and gemini-3.5-flash both return 429 quota errors
    on this key; gemini-2.5-flash is still listed but its generate
    calls hang from this sandbox, so lite is the working default.)
    Raises RuntimeError with a plain message (never the key) when no key
    is set, the API errors, or the response is not a JSON list.
    """
    model = model or os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Export it in your shell "
            "(export GEMINI_API_KEY=...) and retry; the key is never "
            "stored in this repo.")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    body = {
        "contents": [{"parts": [{"text": build_prompt(text)}]}],
        # responseMimeType application/json = structured JSON output.
        # No temperature: Gemini 3.6+ ignores/deprecates sampling params.
        "generationConfig": {"responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Gemini API error {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini request failed: {exc.reason}")
    try:
        text_out = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Gemini returned no text to parse.")
    try:
        data = json.loads(text_out)
    except json.JSONDecodeError:
        raise RuntimeError("Gemini did not return valid JSON.")
    if not isinstance(data, list):
        raise RuntimeError("Gemini did not return a JSON list.")
    return data
