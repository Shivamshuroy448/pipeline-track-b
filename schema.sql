-- Track B schema: patient-reported health data, stored over time.
-- Design: one row per raw report (never overwritten), one row per extracted
-- symptom event. The raw text is always kept, so any parse can be re-checked
-- or re-run. Questionnaire answers live on the report row; free text lives
-- there too. Validation flags live on the event row, never silently dropped.

CREATE TABLE IF NOT EXISTS patients (
    patient_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    age             INTEGER,
    sex             TEXT,
    diagnosis       TEXT,
    treatment       TEXT,
    start_date      TEXT,            -- YYYY-MM-DD, first treatment day
    weight_start_kg REAL,
    weight_alert_kg REAL             -- alert line: 5% below start weight
);

CREATE TABLE IF NOT EXISTS medications (
    med_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    name       TEXT NOT NULL,
    purpose    TEXT,                 -- e.g. antiemetic
    start_date TEXT,
    end_date   TEXT                  -- NULL = still taking it
);

CREATE TABLE IF NOT EXISTS medication_changes (
    change_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL REFERENCES patients(patient_id),
    old_med     TEXT,
    new_med     TEXT,
    change_date TEXT NOT NULL,       -- YYYY-MM-DD
    reason      TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    report_id     TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(patient_id),
    reported_at   TEXT NOT NULL,     -- ISO timestamp
    source        TEXT,              -- app_free_text | questionnaire | both
    free_text     TEXT,              -- NULL when questionnaire-only
    q_nausea      INTEGER,           -- questionnaire 0-10, NULL if not asked
    q_vomiting_episodes INTEGER,
    q_pain        INTEGER,
    q_mouth_sores INTEGER,
    q_swallowing  INTEGER,
    q_weight_kg   REAL
);

CREATE TABLE IF NOT EXISTS symptom_events (
    event_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id          TEXT NOT NULL REFERENCES reports(report_id),
    patient_id         TEXT NOT NULL REFERENCES patients(patient_id),
    symptom            TEXT NOT NULL,  -- nausea | vomiting | mouth_sores |
                                       -- pain | swallowing | fatigue | weight
    severity           INTEGER,        -- 0-10, NULL when not stated
    frequency_per_day  INTEGER,        -- NULL when not stated
    timing             TEXT,           -- e.g. "after dinner", NULL if unknown
    related_medication TEXT,           -- medication named in the report
    confidence         REAL,           -- 0-1, see parser.py
    validation_flags   TEXT,           -- comma-separated, or empty string
    weight_kg          REAL,           -- measured weight, weight events only
    extracted_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_patient ON symptom_events(patient_id);
CREATE INDEX IF NOT EXISTS idx_events_symptom ON symptom_events(symptom);
CREATE INDEX IF NOT EXISTS idx_reports_patient ON reports(patient_id, reported_at);
