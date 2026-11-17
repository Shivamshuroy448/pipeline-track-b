"""
Dr.Tracker provider console — Track B prototype (Dash).

Run:  python app.py        ->  http://127.0.0.1:8050
If tracker.db is missing it is built first (generate_data + build_db).

The dashboard is built around one question: a provider has 30 seconds
before walking into the room. What must be obvious?
  1. Is this patient getting better or worse?   (status banner)
  2. What needs attention right now?            (alerts + open flags)
  3. What changed, and when?                    (trend chart, med-change line)
Everything else — raw text, per-event confidence — is one click down,
not in the way.
"""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dash_table, dcc, html
from dash.dependencies import Input, Output

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "tracker.db")

if not os.path.exists(DB_PATH):
    # Build from the project dir (no chdir: the subprocess gets cwd=BASE).
    subprocess.run([sys.executable, "generate_data.py"], check=True,
                   cwd=BASE)
    subprocess.run([sys.executable, "build_db.py"], check=True, cwd=BASE)


def load(patient_id):
    conn = sqlite3.connect(DB_PATH)
    patients = pd.read_sql("SELECT * FROM patients", conn)
    reports = pd.read_sql(
        "SELECT * FROM reports WHERE patient_id = ? ORDER BY reported_at",
        conn, params=(patient_id,))
    events = pd.read_sql(
        "SELECT e.*, r.reported_at FROM symptom_events e "
        "JOIN reports r ON r.report_id = e.report_id "
        "WHERE e.patient_id = ? ORDER BY r.reported_at",
        conn, params=(patient_id,))
    changes = pd.read_sql(
        "SELECT * FROM medication_changes WHERE patient_id = ?",
        conn, params=(patient_id,))
    conn.close()
    return patients, reports, events, changes


def patient_status(events):
    """Worsening / Stable / Improving from the last 7 days vs the prior 7."""
    sev = events[events["severity"].notna()].copy()
    if sev.empty:
        return "No data", "#6b7280"
    sev["date"] = pd.to_datetime(sev["reported_at"]).dt.date
    latest = sev["date"].max()
    recent = sev[sev["date"] > latest - pd.Timedelta(days=7)]["severity"].mean()
    prior = sev[(sev["date"] <= latest - pd.Timedelta(days=7)) &
                (sev["date"] > latest - pd.Timedelta(days=14))]["severity"].mean()
    if pd.isna(prior):
        return "Stable — no prior week to compare", "#d97706"
    if recent - prior >= 1.5:
        return "Worsening", "#dc2626"
    if prior - recent >= 1.5:
        return "Improving", "#16a34a"
    return "Stable", "#d97706"


def trend_figure(events, changes):
    fig = go.Figure()
    sev = events[(events["severity"].notna()) &
                 (events["symptom"] != "unparsed")]
    for symptom, grp in sev.groupby("symptom"):
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(grp["reported_at"]), y=grp["severity"],
            mode="lines+markers", name=symptom.replace("_", " ")))
    for _, ch in changes.iterrows():
        fig.add_vline(x=datetime.fromisoformat(ch["change_date"]),
                      line_dash="dash", line_color="#dc2626",
                      annotation_text=f"Med change: {ch['old_med']} → "
                                      f"{ch['new_med']}",
                      annotation_position="top left")
    fig.update_layout(title="Symptom severity over time (0–10)",
                      xaxis_title="Date", yaxis_title="Severity",
                      yaxis=dict(range=[0, 10]), height=340,
                      margin=dict(l=40, r=20, t=50, b=40),
                      legend=dict(orientation="h", y=-0.2))
    return fig


def vomiting_figure(events):
    vom = events[events["symptom"] == "vomiting"].copy()
    if vom.empty or vom["frequency_per_day"].isna().all():
        return go.Figure().update_layout(
            title="Vomiting episodes per week — no episodes recorded")
    vom["week"] = pd.to_datetime(vom["reported_at"]).dt.strftime("%Y-W%W")
    weekly = vom.groupby("week")["frequency_per_day"].sum().reset_index()
    fig = go.Figure(go.Bar(x=weekly["week"], y=weekly["frequency_per_day"]))
    fig.update_layout(title="Vomiting episodes per week (reported days)",
                      xaxis_title="Week", yaxis_title="Episodes",
                      height=300, margin=dict(l=40, r=20, t=50, b=40))
    return fig


def weight_figure(events, patient):
    w = events[(events["symptom"] == "weight") &
               (events["weight_kg"].notna())].copy()
    if w.empty:
        return go.Figure().update_layout(
            title="Weight trend — no weight recorded")
    w["date"] = pd.to_datetime(w["reported_at"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=w["date"], y=w["weight_kg"],
                             mode="lines+markers", name="Weight (kg)"))
    fig.add_hline(y=patient["weight_alert_kg"].iloc[0], line_dash="dash",
                  line_color="#dc2626",
                  annotation_text="Alert line (5% loss)",
                  annotation_position="bottom right")
    fig.update_layout(title="Weight trend (kg)",
                      xaxis_title="Date", yaxis_title="kg",
                      height=300, margin=dict(l=40, r=20, t=50, b=40))
    return fig


app = Dash(__name__)
app.title = "Dr.Tracker — Provider Console (Track B prototype)"

with sqlite3.connect(DB_PATH) as _conn:
    PATIENTS = pd.read_sql(
        "SELECT patient_id, name FROM patients", _conn).to_dict("records")
OPTIONS = [{"label": f"{p['name']} ({p['patient_id']})",
            "value": p["patient_id"]} for p in PATIENTS]

app.layout = html.Div([
    html.H1("Dr.Tracker — Provider Console"),
    html.P("Track B prototype · Patient-reported data: store, manage & chart · "
           "All data is synthetic. No real patient information.",
           style={"color": "#6b7280"}),
    dcc.Dropdown(id="patient", options=OPTIONS, value="P002",
                 clearable=False, style={"maxWidth": "420px"}),
    html.Div(id="status-banner", style={"marginTop": "16px"}),
    html.Div(id="alerts", style={"marginTop": "8px"}),
    dcc.Graph(id="trend"),
    html.Div([
        html.Div([dcc.Graph(id="vomiting")],
                 style={"width": "48%", "display": "inline-block"}),
        html.Div([dcc.Graph(id="weight")],
                 style={"width": "48%", "display": "inline-block",
                        "float": "right"}),
    ]),
    html.H3("Needs review — validation flags"),
    html.P("Events the parser flagged instead of silently trusting. "
           "Click through to the raw report to judge for yourself.",
           style={"color": "#6b7280"}),
    dash_table.DataTable(id="flags", page_size=8,
                         style_cell={"textAlign": "left", "fontSize": "13px"},
                         style_header={"fontWeight": "bold"}),
    html.H3("Raw reports — what the patient actually wrote"),
    html.Div(id="raw-reports"),
], style={"maxWidth": "1100px", "margin": "0 auto",
          "fontFamily": "system-ui, sans-serif", "padding": "0 16px 40px"})


@app.callback(
    [Output("status-banner", "children"),
     Output("alerts", "children"),
     Output("trend", "figure"),
     Output("vomiting", "figure"),
     Output("weight", "figure"),
     Output("flags", "data"),
     Output("flags", "columns"),
     Output("raw-reports", "children")],
    [Input("patient", "value")])
def update(patient_id):
    patients, reports, events, changes = load(patient_id)
    patient = patients[patients["patient_id"] == patient_id]
    name = patient["name"].iloc[0]
    status, color = patient_status(events)

    # Vomiting this week (last 7 days of data).
    vom = events[events["symptom"] == "vomiting"]
    latest = pd.to_datetime(events["reported_at"]).max() \
        if not events.empty else None
    vom_week = 0
    if not vom.empty and latest is not None:
        recent = vom[pd.to_datetime(vom["reported_at"]) >
                     latest - pd.Timedelta(days=7)]
        vom_week = int(recent["frequency_per_day"].fillna(0).sum())

    worst = events[events["severity"].notna()]
    worst_txt = "—"
    if not worst.empty:
        row = worst.sort_values("severity", ascending=False).iloc[0]
        worst_txt = f"{row['symptom'].replace('_', ' ')} {int(row['severity'])}/10"

    flagged = events[(events["validation_flags"] != "") &
                     (events["validation_flags"] != "questionnaire_only")]

    banner = html.Div([
        html.Strong(f"{name} — {status}  "),
        html.Span(f"· Vomiting this week: {vom_week}  · "
                  f"Worst symptom: {worst_txt}  · "
                  f"Open flags: {len(flagged)}"),
    ], style={"background": color, "color": "white", "padding": "12px 16px",
              "borderRadius": "8px", "fontSize": "15px"})

    alerts = []
    w = events[(events["symptom"] == "weight") &
               (events["weight_kg"].notna())]
    if not w.empty:
        latest_w = w.sort_values("reported_at").iloc[-1]["weight_kg"]
        alert_line = patient["weight_alert_kg"].iloc[0]
        start_w = patient["weight_start_kg"].iloc[0]
        if latest_w <= alert_line:
            alerts.append(html.Div(
                f"⚠ Weight alert: {latest_w} kg, down "
                f"{round(start_w - latest_w, 1)} kg from start "
                f"({round(100 * (start_w - latest_w) / start_w, 1)}% loss) — "
                f"below the 5% alert line.",
                style={"background": "#fef2f2", "border": "1px solid #dc2626",
                       "color": "#991b1b", "padding": "10px 14px",
                       "borderRadius": "8px"}))
    if vom_week >= 4:
        alerts.append(html.Div(
            f"⚠ Vomiting spike: {vom_week} episodes in the last 7 days.",
            style={"background": "#fef2f2", "border": "1px solid #dc2626",
                   "color": "#991b1b", "padding": "10px 14px",
                   "borderRadius": "8px", "marginTop": "6px"}))
    if not alerts:
        alerts = [html.Div("No active alerts.",
                           style={"color": "#16a34a"})]

    flag_rows = []
    for _, e in flagged.iterrows():
        flag_rows.append({
            "Date": str(e["reported_at"])[:10],
            "Symptom": e["symptom"].replace("_", " "),
            "Severity": "" if pd.isna(e["severity"]) else int(e["severity"]),
            "Confidence": e["confidence"],
            "Flag": e["validation_flags"],
        })
    columns = [{"name": c, "id": c} for c in
               ["Date", "Symptom", "Severity", "Confidence", "Flag"]]

    raw = []
    for _, r in reports.tail(8).iloc[::-1].iterrows():
        ev = events[events["report_id"] == r["report_id"]]
        parsed = "; ".join(
            f"{e['symptom'].replace('_', ' ')}"
            + (f" {int(e['severity'])}/10" if pd.notna(e["severity"]) else "")
            + (f" ×{int(e['frequency_per_day'])}" if pd.notna(e["frequency_per_day"]) else "")
            + (f" (conf {e['confidence']})" if e["confidence"] else "")
            for _, e in ev.iterrows())
        raw.append(html.Div([
            html.Strong(str(r["reported_at"])[:10] + "  "),
            html.Span(r["free_text"] or "(questionnaire only)",
                      style={"fontStyle": "italic"}),
            html.Br(),
            html.Small("Parsed: " + (parsed or "—"),
                       style={"color": "#6b7280"}),
        ], style={"borderBottom": "1px solid #e5e7eb",
                  "padding": "8px 0"}))

    return (banner, alerts, trend_figure(events, changes),
            vomiting_figure(events), weight_figure(events, patient),
            flag_rows, columns, raw)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
