"""
Synthetic patient-reported data generator — Track B (oncology demo scenario).

Scenario: head & neck radiation + chemotherapy (mirrors the Dr.Tracker oncology
demo: daily logs of mouth sores, pain and swallowing, plus a weight trend with
an alert line). All patients, reports and values are invented.

Four patients, six weeks of treatment starting Mon 2026-09-07, two reports per
week (Mon + Thu). Each report has free text and/or a questionnaire. A few
hand-written edge cases (vague, conflicting, missing severity) are appended
at the end so the parser's validation layer has something real to catch.

Deterministic: seeded RNG, so re-running produces the same dataset.
Run:  python generate_data.py   ->  writes data/reports.json
"""

import json
import random
from datetime import date, timedelta

RNG = random.Random(20260907)
START = date(2026, 9, 7)  # Monday, week 1 of treatment
WEEKS = 6

PATIENTS = [
    {
        "patient_id": "P001",
        "name": "Maria Santos",
        "age": 58,
        "sex": "F",
        "diagnosis": "Oropharyngeal cancer",
        "treatment": "Cisplatin + radiation",
        "start_date": "2026-09-07",
        "weight_start_kg": 68.0,
        "weight_alert_kg": 64.6,  # 5% loss
    },
    {
        "patient_id": "P002",
        "name": "James Okafor",
        "age": 63,
        "sex": "M",
        "diagnosis": "Laryngeal cancer",
        "treatment": "Carboplatin + radiation",
        "start_date": "2026-09-07",
        "weight_start_kg": 84.0,
        "weight_alert_kg": 79.8,
    },
    {
        "patient_id": "P003",
        "name": "Elena Petrova",
        "age": 47,
        "sex": "F",
        "diagnosis": "Nasopharyngeal cancer",
        "treatment": "Cisplatin + radiation",
        "start_date": "2026-09-07",
        "weight_start_kg": 61.0,
        "weight_alert_kg": 58.0,
    },
    {
        "patient_id": "P004",
        "name": "David Chen",
        "age": 71,
        "sex": "M",
        "diagnosis": "Hypopharyngeal cancer",
        "treatment": "Cisplatin + radiation",
        "start_date": "2026-09-07",
        "weight_start_kg": 78.0,
        "weight_alert_kg": 74.1,  # 5% loss — crossed in week 6
    },
]

MEDICATIONS = [
    # patient P002 switches antiemetic in week 3 after vomiting worsens
    {"patient_id": "P002", "name": "Ondansetron", "purpose": "antiemetic",
     "start_date": "2026-09-07", "end_date": "2026-09-27"},
    {"patient_id": "P002", "name": "Aprepitant", "purpose": "antiemetic",
     "start_date": "2026-09-28", "end_date": None},
    {"patient_id": "P001", "name": "Ondansetron", "purpose": "antiemetic",
     "start_date": "2026-09-07", "end_date": None},
    {"patient_id": "P003", "name": "Ondansetron", "purpose": "antiemetic",
     "start_date": "2026-09-07", "end_date": None},
    {"patient_id": "P004", "name": "Ondansetron", "purpose": "antiemetic",
     "start_date": "2026-09-07", "end_date": None},
]

MEDICATION_CHANGES = [
    {"patient_id": "P002", "old_med": "Ondansetron", "new_med": "Aprepitant",
     "change_date": "2026-09-28",
     "reason": "Vomiting 4-5 episodes/week on ondansetron; switched to aprepitant"},
]

# --- symptom trajectories: severity 0-10 by week (1-indexed) -----------------
# Radiation side effects build over weeks 2-4, then plateau. P002 improves
# after the week-3 antiemetic switch; P004 loses weight steadily.
TRAJECTORY = {
    "P001": {"nausea": [3, 5, 6, 6, 5, 4], "vomiting": [0, 1, 1, 0, 1, 0],
             "pain": [2, 4, 5, 6, 6, 5], "mouth_sores": [0, 2, 4, 6, 6, 5],
             "swallowing": [1, 3, 4, 5, 5, 4], "fatigue": [3, 4, 5, 6, 5, 5],
             "weight_delta": [0, -0.4, -0.8, -1.2, -1.6, -1.9]},
    "P002": {"nausea": [4, 6, 8, 5, 3, 2], "vomiting": [1, 3, 5, 2, 1, 0],
             "pain": [2, 3, 4, 4, 3, 3], "mouth_sores": [0, 1, 3, 4, 4, 3],
             "swallowing": [1, 2, 3, 3, 3, 2], "fatigue": [3, 5, 6, 5, 4, 4],
             "weight_delta": [0, -0.6, -1.4, -1.8, -2.0, -2.1]},
    "P003": {"nausea": [2, 4, 5, 5, 4, 4], "vomiting": [0, 1, 2, 1, 1, 0],
             "pain": [3, 4, 5, 5, 5, 4], "mouth_sores": [1, 2, 3, 5, 5, 4],
             "swallowing": [2, 3, 4, 5, 4, 4], "fatigue": [4, 5, 5, 6, 5, 5],
             "weight_delta": [0, -0.3, -0.7, -1.0, -1.3, -1.5]},
    "P004": {"nausea": [3, 4, 5, 5, 4, 4], "vomiting": [0, 1, 1, 1, 0, 0],
             "pain": [2, 3, 4, 5, 5, 5], "mouth_sores": [0, 2, 3, 4, 5, 5],
             "swallowing": [1, 2, 4, 5, 6, 6], "fatigue": [3, 4, 5, 6, 6, 6],
             "weight_delta": [0, -0.9, -1.8, -2.7, -3.6, -4.5]},
}

SEV_WORD = {0: "none", 1: "very mild", 2: "mild", 3: "mild", 4: "moderate",
            5: "moderate", 6: "quite bad", 7: "bad", 8: "severe",
            9: "very severe", 10: "the worst"}

NAUSEA_T = [
    "Felt nauseous most of the day, {sev} nausea.",
    "Nausea was {sev} today, worst after eating.",
    "Felt queasy all morning, {sev}.",
    "Nausea {sev} — took ondansetron and it eased a bit.",
]
VOMIT_T = [
    "Threw up {n} after dinner.",
    "Vomited {n} today.",
    "Threw up {n}, mostly in the morning.",
]
PAIN_T = [
    "Throat pain was {sev}, about {num}/10.",
    "Pain {sev} today, swallowing hurts.",
    "Pain around {num}/10, worse when I eat.",
]
SORES_T = [
    "Mouth sores are {sev}, eating is painful.",
    "More mouth sores today, {sev}. Using the mouthwash.",
    "Sores in my mouth {sev}, {num}/10.",
]
SWALLOW_T = [
    "Swallowing is {sev}, food gets stuck.",
    "Hard to swallow today, {sev}. Sticking to liquids.",
    "Trouble swallowing, about {num}/10.",
]
FATIGUE_T = [
    "Exhausted all day, barely got out of bed.",
    "Very tired today, {sev} fatigue.",
    "Low energy, {sev}.",
]
WEIGHT_T = [
    "Weighed myself: {w} kg, down a bit.",
    "Lost some weight, {w} kg now.",
]
GOOD_T = [
    "Pretty good day overall, symptoms mild.",
    "Feeling better today, nausea mostly gone.",
    "Good day, ate normally and kept everything down.",
]


def sev_text(value):
    return SEV_WORD[max(0, min(10, int(round(value))))]


def jitter(value, spread=1):
    return max(0, min(10, value + RNG.randint(-spread, spread)))


def build_free_text(pid, week, traj, weight_kg):
    """Compose one realistic free-text report from the week's trajectory."""
    parts = []
    nausea = jitter(traj["nausea"][week - 1])
    vomits = max(0, traj["vomiting"][week - 1] + RNG.randint(-1, 1))
    pain = jitter(traj["pain"][week - 1])
    sores = jitter(traj["mouth_sores"][week - 1])
    swallow = jitter(traj["swallowing"][week - 1])
    fatigue = jitter(traj["fatigue"][week - 1])

    if nausea >= 3:
        parts.append(RNG.choice(NAUSEA_T).format(
            sev=sev_text(nausea), num=nausea))
    if vomits >= 1:
        n_word = {1: "once", 2: "twice", 3: "three times",
                  4: "four times", 5: "five times"}.get(vomits, f"{vomits} times")
        parts.append(RNG.choice(VOMIT_T).format(n=n_word))
    if pain >= 3:
        parts.append(RNG.choice(PAIN_T).format(sev=sev_text(pain), num=pain))
    if sores >= 2:
        parts.append(RNG.choice(SORES_T).format(sev=sev_text(sores), num=sores))
    if swallow >= 3:
        parts.append(RNG.choice(SWALLOW_T).format(
            sev=sev_text(swallow), num=swallow))
    if fatigue >= 5 and RNG.random() < 0.6:
        parts.append(RNG.choice(FATIGUE_T).format(
            sev=sev_text(fatigue), num=fatigue))
    if RNG.random() < 0.3:
        parts.append(RNG.choice(WEIGHT_T).format(w=round(weight_kg, 1)))
    if not parts:
        parts.append(RNG.choice(GOOD_T))
    return " ".join(parts)


def build_questionnaire(pid, week, traj, weight_kg):
    return {
        "nausea": int(jitter(traj["nausea"][week - 1])),
        "vomiting_episodes": max(0, traj["vomiting"][week - 1] + RNG.randint(-1, 1)),
        "pain": int(jitter(traj["pain"][week - 1])),
        "mouth_sores": int(jitter(traj["mouth_sores"][week - 1])),
        "swallowing": int(jitter(traj["swallowing"][week - 1])),
        "weight_kg": round(weight_kg, 1),
    }


def main():
    reports = []
    rid = 1
    for patient in PATIENTS:
        pid = patient["patient_id"]
        traj = TRAJECTORY[pid]
        for week in range(1, WEEKS + 1):
            for day_offset in (0, 3):  # Monday + Thursday
                day = START + timedelta(weeks=week - 1, days=day_offset)
                weight = patient["weight_start_kg"] + traj["weight_delta"][week - 1]
                # 70% of reports carry both text + questionnaire; the rest
                # carry one or the other, so the parser must handle gaps.
                roll = RNG.random()
                has_text = roll < 0.85
                has_q = roll > 0.15
                reports.append({
                    "report_id": f"R{rid:03d}",
                    "patient_id": pid,
                    "reported_at": f"{day}T19:30:00",
                    "source": ("app_free_text" if has_text and not has_q else
                               "questionnaire" if has_q and not has_text else
                               "app_free_text+questionnaire"),
                    "free_text": build_free_text(pid, week, traj, weight) if has_text else None,
                    "questionnaire": (build_questionnaire(pid, week, traj, weight)
                                      if has_q else None),
                })
                rid += 1

    # --- hand-written edge cases the parser must flag, not silently accept --
    edge_cases = [
        # Vague: no usable severity anywhere.
        {"report_id": f"R{rid:03d}", "patient_id": "P003",
         "reported_at": "2026-09-23T20:05:00", "source": "app_free_text",
         "free_text": "Felt bad all day, not great. Hard to say how bad.",
         "questionnaire": None},
        # Conflicting: text says twice, questionnaire says 0 episodes.
        {"report_id": f"R{rid + 1:03d}", "patient_id": "P003",
         "reported_at": "2026-09-30T19:45:00",
         "source": "app_free_text+questionnaire",
         "free_text": "Threw up twice after dinner, felt nauseous all morning.",
         "questionnaire": {"nausea": 6, "vomiting_episodes": 0, "pain": 4,
                           "mouth_sores": 3, "swallowing": 4, "weight_kg": 59.8}},
        # Missing severity + frequency guess ("a few times").
        {"report_id": f"R{rid + 2:03d}", "patient_id": "P001",
         "reported_at": "2026-10-07T18:20:00", "source": "app_free_text",
         "free_text": "Threw up a few times today and my mouth hurts.",
         "questionnaire": None},
        # Weight below the alert line, stated in pounds (unit handling).
        {"report_id": f"R{rid + 3:03d}", "patient_id": "P004",
         "reported_at": "2026-10-14T08:10:00", "source": "app_free_text",
         "free_text": "Weighed myself this morning: 163 pounds. Eating is very hard, swallowing is the worst it has been.",
         "questionnaire": {"nausea": 4, "vomiting_episodes": 0, "pain": 5,
                           "mouth_sores": 5, "swallowing": 8, "weight_kg": 73.9}},
    ]
    reports.extend(edge_cases)

    out = {
        "patients": PATIENTS,
        "medications": MEDICATIONS,
        "medication_changes": MEDICATION_CHANGES,
        "reports": reports,
    }
    with open("data/reports.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"wrote data/reports.json: {len(PATIENTS)} patients, "
          f"{len(reports)} reports")


if __name__ == "__main__":
    main()
