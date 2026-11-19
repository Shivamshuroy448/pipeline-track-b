"""
Dr.Tracker provider console — Track B prototype (Dash).

Same UI language as the Pipeline Dr.Tracker demo: light warm background,
white cards, teal accent, generous rounding. Two views, one app:

  Clinic console  — left rail, stats row, patients table, patient detail
                      (trend + vomiting + weight charts, flags, raw reports).
  Patient app     — phone-frame "Today" view for the selected patient,
                      with a live "Log a report" box: type a free-text
                      report and watch the parser (rule-based or LLM)
                      turn it into structured events.

Run:  python app.py        ->  http://127.0.0.1:8050
If tracker.db is missing it is built first (generate_data + build_db).
LLM extraction in the phone view needs GEMINI_API_KEY in the
environment; without it the LLM option falls back to rule-based and
says so.
"""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dash_table, dcc, html
from dash.dependencies import Input, Output, State

from parser import parse_report, parse_with_llm

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "tracker.db")

if not os.path.exists(DB_PATH):
    # Build from the project dir (no chdir: the subprocess gets cwd=BASE).
    subprocess.run([sys.executable, "generate_data.py"], check=True,
                   cwd=BASE)
    subprocess.run([sys.executable, "build_db.py"], check=True, cwd=BASE)

# ---- Theme: light Dr.Tracker console (matches the Pipeline demo) ----------
BG = "#f5f2ee"          # warm off-white page
SURFACE = "#ffffff"     # cards
PALE_TEAL = "#e8f2f0"   # selected / tinted surfaces
BORDER = "#e7e2d9"      # hairline borders
TEXT = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#2b6962"      # teal: primary buttons / links
AMBER = "#c96c1d"
RED = "#dc2626"
RED_BG = "#fef2f2"
GREEN = "#15803d"
FONT = ("system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif")
MONO = ("ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, monospace")

CARD = {"background": SURFACE, "border": f"1px solid {BORDER}",
        "borderRadius": "16px", "padding": "16px 18px",
        "marginTop": "16px",
        "boxShadow": "0 1px 3px rgba(31, 41, 55, 0.06)"}
RADIUS_BTN = "10px"


def light_fig(fig, title, height):
    """Shared light styling for every chart."""
    fig.update_layout(
        template="plotly_white",
        title=dict(text=title, font=dict(color=TEXT, size=15)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family=FONT), height=height,
        margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER))
    return fig


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
        return "Stable — no prior week to compare", AMBER
    if recent - prior >= 1.5:
        return "Worsening", RED
    if prior - recent >= 1.5:
        return "Improving", GREEN
    return "Stable", "#b45309"


def _vomiting_last_7d(events):
    vom = events[events["symptom"] == "vomiting"]
    if vom.empty:
        return 0
    latest = pd.to_datetime(events["reported_at"]).max()
    recent = vom[pd.to_datetime(vom["reported_at"]) >
                 latest - pd.Timedelta(days=7)]
    return int(recent["frequency_per_day"].fillna(0).sum())


def _weight_alert(events, patient):
    w = events[(events["symptom"] == "weight") &
               (events["weight_kg"].notna())]
    if w.empty:
        return False
    latest_w = w.sort_values("reported_at").iloc[-1]["weight_kg"]
    return latest_w <= patient["weight_alert_kg"].iloc[0]


def patient_risk(events, patient):
    """High: weight alert or vomiting spike. Medium: open flags. Else Low."""
    if _weight_alert(events, patient) or _vomiting_last_7d(events) >= 4:
        return "High"
    flagged = events[(events["validation_flags"] != "") &
                     (events["validation_flags"] != "questionnaire_only")]
    return "Medium" if len(flagged) else "Low"


def trend_figure(events, changes):
    fig = go.Figure()
    sev = events[(events["severity"].notna()) &
                 (events["symptom"] != "unparsed")]
    palette = {"nausea": ACCENT, "pain": "#d97706", "mouth_sores": "#7c3aed",
               "swallowing": "#2563eb", "fatigue": "#6b7280",
               "vomiting": RED, "weight": AMBER}
    for symptom, grp in sev.groupby("symptom"):
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(grp["reported_at"]), y=grp["severity"],
            mode="lines+markers", name=symptom.replace("_", " "),
            line=dict(color=palette.get(symptom, TEXT), width=2.5),
            marker=dict(size=6)))
    for _, ch in changes.iterrows():
        fig.add_vline(x=datetime.fromisoformat(ch["change_date"]),
                      line_dash="dash", line_color=RED,
                      annotation_text=f"Med change: {ch['old_med']} → "
                                      f"{ch['new_med']}",
                      annotation_position="top left",
                      annotation_font_color=RED)
    fig.update_layout(yaxis=dict(range=[0, 10]),
                      legend=dict(orientation="h", y=-0.2))
    return light_fig(fig, "Symptom severity over time (0–10)", 340)


def vomiting_figure(events):
    vom = events[events["symptom"] == "vomiting"].copy()
    if vom.empty or vom["frequency_per_day"].isna().all():
        fig = go.Figure()
        return light_fig(fig, "Vomiting episodes per week — none recorded",
                         300)
    vom["week"] = pd.to_datetime(vom["reported_at"]).dt.strftime("%Y-W%W")
    weekly = vom.groupby("week")["frequency_per_day"].sum().reset_index()
    fig = go.Figure(go.Bar(x=weekly["week"], y=weekly["frequency_per_day"],
                           marker_color=ACCENT))
    fig.update_layout(xaxis_title="Week", yaxis_title="Episodes")
    return light_fig(fig, "Vomiting episodes per week (reported days)", 300)


def weight_figure(events, patient):
    w = events[(events["symptom"] == "weight") &
               (events["weight_kg"].notna())].copy()
    if w.empty:
        fig = go.Figure()
        return light_fig(fig, "Weight trend — no weight recorded", 300)
    w["date"] = pd.to_datetime(w["reported_at"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=w["date"], y=w["weight_kg"],
                             mode="lines+markers", name="Weight (kg)",
                             line=dict(color=AMBER, width=2.5),
                             marker=dict(size=6)))
    fig.add_hline(y=patient["weight_alert_kg"].iloc[0], line_dash="dash",
                  line_color=RED,
                  annotation_text="Alert line (5% loss)",
                  annotation_position="bottom right",
                  annotation_font_color=RED)
    fig.update_layout(xaxis_title="Date", yaxis_title="kg")
    return light_fig(fig, "Weight trend (kg)", 300)


app = Dash(__name__)
app.title = "Dr.Tracker — Provider Console (Track B prototype)"

with sqlite3.connect(DB_PATH) as _conn:
    PATIENTS = pd.read_sql(
        "SELECT patient_id, name FROM patients", _conn).to_dict("records")
OPTIONS = [{"label": f"{p['name']} ({p['patient_id']})",
            "value": p["patient_id"]} for p in PATIENTS]


def build_patient_rows():
    """One row per patient for the console table, all from tracker.db."""
    conn = sqlite3.connect(DB_PATH)
    patients = pd.read_sql("SELECT * FROM patients", conn)
    rows = []
    for _, p in patients.iterrows():
        pid = p["patient_id"]
        _, reports, events, _ = load(pid)
        status, _ = patient_status(events)
        last = pd.to_datetime(reports["reported_at"]).max()
        n_reports = len(reports)
        n_text = int(reports["free_text"].notna().sum())
        engagement = f"{round(100 * n_text / max(n_reports, 1))}%"
        flagged = events[(events["validation_flags"] != "") &
                         (events["validation_flags"] != "questionnaire_only")]
        risk = patient_risk(events, patients[patients["patient_id"] == pid])
        rows.append({
            "Patient": f"{p['name']} · {int(p['age'])} · "
                       f"{p['diagnosis'].replace(' cancer', '')}",
            "Plan": p["treatment"].split(" + ")[0],
            "Status": status.split(" — ")[0],
            "Last check-in": last.strftime("%d %b %Y"),
            "Engagement": engagement,
            "Risk": risk,
            "Messages": f"{len(flagged)} new" if len(flagged) else "—",
            "Review": "Review now",
            "_id": pid,
        })
    conn.close()
    return rows


PATIENT_ROWS = build_patient_rows()
N_ALERTS = sum(1 for r in PATIENT_ROWS if r["Risk"] == "High")
N_FLAGS = sum(int(r["Messages"].split(" ")[0])
              for r in PATIENT_ROWS if r["Messages"] != "—")
N_REPORTS = sum(len(load(r["_id"])[1]) for r in PATIENT_ROWS)

TABLE_COLUMNS = [{"name": c, "id": c} for c in
                 ["Patient", "Plan", "Status", "Last check-in",
                  "Engagement", "Risk", "Messages", "Review"]]

NAV_BTN = {"display": "block", "width": "100%", "textAlign": "left",
           "background": "none", "border": "none", "padding": "10px 12px",
           "borderRadius": RADIUS_BTN, "fontSize": "14px", "color": TEXT,
           "cursor": "pointer", "fontFamily": FONT}
NAV_BTN_ACTIVE = dict(NAV_BTN, background=PALE_TEAL, color=ACCENT,
                      fontWeight="600")


def stat_card(value, label):
    return html.Div([
        html.Div(str(value), style={"fontSize": "28px", "fontWeight": "700"}),
        html.Div(label, style={"color": MUTED, "fontSize": "13px",
                               "marginTop": "2px"}),
    ], style=dict(CARD, marginTop="0", flex="1"))


def toggle_style(active):
    base = {"padding": "8px 16px", "borderRadius": "999px", "border": "none",
            "fontSize": "13px", "cursor": "pointer", "fontFamily": FONT}
    if active:
        return dict(base, background=ACCENT, color="white",
                    fontWeight="600")
    return dict(base, background="transparent", color=TEXT)


app.layout = html.Div([
    dcc.Store(id="view-store", data="console"),
    dcc.Store(id="table-order-store",
              data=[r["_id"] for r in PATIENT_ROWS]),
    # ---- Left rail ------------------------------------------------------
    html.Div([
        html.Div([
            html.Span("Dr.Tracker", style={"fontSize": "19px",
                                           "fontWeight": "700"}),
            html.Span("Clinic console",
                      style={"fontSize": "11px", "color": ACCENT,
                             "background": PALE_TEAL, "borderRadius": "999px",
                             "padding": "3px 8px", "marginLeft": "8px"}),
        ], style={"padding": "4px 4px 16px"}),
        dcc.Input(id="patient-search", type="text",
                  placeholder="Search patient or record…",
                  style={"width": "100%", "padding": "9px 12px",
                         "borderRadius": RADIUS_BTN,
                         "border": f"1px solid {BORDER}", "fontSize": "13px",
                         "fontFamily": FONT, "boxSizing": "border-box"}),
        html.Div([
            html.Button("Dashboard", id="nav-dashboard", n_clicks=0,
                        style=NAV_BTN_ACTIVE),
            html.Button("Patients", id="nav-patients", n_clicks=0,
                        style=NAV_BTN),
            html.Button("Patient app", id="nav-patientapp", n_clicks=0,
                        style=NAV_BTN),
        ], style={"marginTop": "16px"}),
        html.Div([
            html.Div("Clinic plan: Growth",
                     style={"fontSize": "13px", "fontWeight": "600"}),
            html.Div("4 patients · sample data",
                     style={"fontSize": "12px", "color": MUTED,
                            "marginTop": "2px"}),
            html.Hr(style={"border": f"1px solid {BORDER}",
                           "margin": "14px 0 10px"}),
            html.Div("Dr. James Whitaker",
                     style={"fontSize": "13px", "fontWeight": "600"}),
            html.Div("Oncology · Head of Unit",
                     style={"fontSize": "12px", "color": MUTED}),
        ], style={"position": "absolute", "bottom": "20px", "left": "20px",
                  "right": "20px"}),
    ], style={"width": "260px", "minWidth": "260px", "background": SURFACE,
              "borderRight": f"1px solid {BORDER}", "padding": "20px",
              "position": "relative", "minHeight": "100vh",
              "boxSizing": "border-box"}),
    # ---- Main panel -----------------------------------------------------
    html.Div([
        # Top bar
        html.Div([
            html.Div([
                html.H1("Dr. James Whitaker's practice",
                        style={"margin": "0", "fontSize": "22px"}),
                html.P("Clinic console — sample data, no real patients",
                       style={"margin": "4px 0 0", "color": MUTED,
                              "fontSize": "13px"}),
            ]),
            html.Div([
                html.Button("Clinic console", id="toggle-console",
                            n_clicks=0, style=toggle_style(True)),
                html.Button("Patient app", id="toggle-patient",
                            n_clicks=0, style=toggle_style(False)),
            ], style={"background": SURFACE, "border": f"1px solid {BORDER}",
                      "borderRadius": "999px", "padding": "3px"}),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "center", "gap": "16px"}),
        html.Div([
            html.Label("Patient", style={"color": MUTED, "fontSize": "12px",
                                         "letterSpacing": "1px"}),
            dcc.Dropdown(id="patient", options=OPTIONS, value="P002",
                         clearable=False,
                         style={"maxWidth": "420px", "marginTop": "6px"}),
        ], style={"marginTop": "18px"}),
        # ---- Console view ----
        html.Div([
            html.Div([
                stat_card(len(PATIENT_ROWS), "Patients"),
                stat_card(N_ALERTS, "Alerts"),
                stat_card(N_FLAGS, "Open flags"),
                stat_card(N_REPORTS, "Reports"),
            ], style={"display": "flex", "gap": "16px", "marginTop": "16px"}),
            html.Div([
                html.H3("Patients", style={"margin": "0 0 12px",
                                           "fontSize": "16px"}),
                dash_table.DataTable(
                    id="patients-table", columns=TABLE_COLUMNS,
                    data=PATIENT_ROWS,
                    style_cell={"textAlign": "left", "fontSize": "13px",
                                "background": SURFACE, "color": TEXT,
                                "border": f"1px solid {BORDER}",
                                "padding": "10px 12px"},
                    style_header={"fontWeight": "bold",
                                  "background": "#faf8f5", "color": MUTED,
                                  "border": f"1px solid {BORDER}"},
                    style_data_conditional=[
                        {"if": {"column_id": "Risk",
                                "filter_query": '{Risk} = "High"'},
                         "color": RED, "fontWeight": "600"},
                        {"if": {"column_id": "Risk",
                                "filter_query": '{Risk} = "Medium"'},
                         "color": AMBER, "fontWeight": "600"},
                        {"if": {"column_id": "Review"},
                         "color": ACCENT, "fontWeight": "600"},
                    ],
                    style_cell_conditional=[
                        {"if": {"column_id": "Review"}, "cursor": "pointer"}],
                ),
                html.P(f"Showing {len(PATIENT_ROWS)} of "
                       f"{len(PATIENT_ROWS)} patients",
                       style={"color": MUTED, "fontSize": "12px",
                              "margin": "10px 0 0"}),
            ], style=CARD),
            html.Div(id="status-banner", style={"marginTop": "16px"}),
            html.Div(id="alerts", style={"marginTop": "8px"}),
            html.Div([dcc.Graph(id="trend")], style=CARD),
            html.Div([
                html.Div([dcc.Graph(id="vomiting")],
                         style={"width": "48%", "display": "inline-block"}),
                html.Div([dcc.Graph(id="weight")],
                         style={"width": "48%", "display": "inline-block",
                                "float": "right"}),
            ], style=CARD),
            html.Div([
                html.H3("Needs review — validation flags",
                        style={"margin": "0 0 4px", "fontSize": "16px"}),
                html.P("Events the parser flagged instead of silently "
                       "trusting. Click through to the raw report to judge "
                       "for yourself.",
                       style={"color": MUTED, "fontSize": "13px",
                              "margin": "0 0 12px"}),
                dash_table.DataTable(
                    id="flags", page_size=8,
                    style_cell={"textAlign": "left", "fontSize": "13px",
                                "background": SURFACE, "color": TEXT,
                                "border": f"1px solid {BORDER}"},
                    style_header={"fontWeight": "bold",
                                  "background": "#faf8f5", "color": MUTED,
                                  "border": f"1px solid {BORDER}"}),
            ], style=CARD),
            html.Div([
                html.H3("Raw reports — what the patient actually wrote",
                        style={"margin": "0 0 6px", "fontSize": "16px"}),
                html.Div(id="raw-reports"),
            ], style=CARD),
            html.Div([
                html.H3("Recent check-ins — last 4",
                        style={"margin": "0 0 6px", "fontSize": "16px"}),
                html.Div(id="recent-checkins"),
            ], style=CARD),
        ], id="console-view"),
        # ---- Patient app view (phone) ----
        html.Div([
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("9:41", style={"fontSize": "12px",
                                                 "fontWeight": "600"}),
                        html.Span("Demo · sample patient",
                                  style={"fontSize": "11px", "color": AMBER}),
                        html.Span("WiFi 100%",
                                  style={"fontSize": "12px"}),
                    ], style={"display": "flex",
                              "justifyContent": "space-between"}),
                    html.Div(id="phone-today"),
                    html.Hr(style={"border": f"1px solid {BORDER}",
                                   "margin": "16px 0"}),
                    html.Div("Log a report",
                             style={"fontSize": "15px", "fontWeight": "700"}),
                    html.P("Type what the patient says, in their own "
                           "words. The parser turns it into structured "
                           "data — right here, live.",
                           style={"color": MUTED, "fontSize": "13px",
                                  "margin": "4px 0 10px"}),
                    dcc.Textarea(
                        id="log-text", placeholder="e.g. Threw up twice "
                        "after dinner, felt nauseous all morning.",
                        style={"width": "100%", "height": "80px",
                               "borderRadius": RADIUS_BTN,
                               "border": f"1px solid {BORDER}",
                               "padding": "10px 12px", "fontSize": "14px",
                               "fontFamily": FONT, "boxSizing": "border-box",
                               "resize": "vertical"}),
                    dcc.Store(id="log-method-store", data="rules"),
                    html.Div([
                        html.Button("Rule-based parser",
                                    id="log-method-rules", n_clicks=0,
                                    style=toggle_style(True)),
                        html.Button("LLM (Gemini)", id="log-method-llm",
                                    n_clicks=0, style=toggle_style(False)),
                    ], style={"marginTop": "10px", "background": SURFACE,
                              "border": f"1px solid {BORDER}",
                              "borderRadius": "999px", "padding": "3px",
                              "display": "inline-block"}),
                    html.Button("Save check-in", id="log-save", n_clicks=0,
                                style={"marginTop": "12px", "width": "100%",
                                       "background": ACCENT, "color": "white",
                                       "border": "none",
                                       "borderRadius": RADIUS_BTN,
                                       "padding": "11px", "fontSize": "14px",
                                       "fontWeight": "600", "cursor": "pointer",
                                       "fontFamily": FONT}),
                    html.Div(id="log-results", style={"marginTop": "12px"}),
                    html.P("Only this clinic sees what you log.",
                           style={"color": MUTED, "fontSize": "12px",
                                  "textAlign": "center", "marginTop": "14px"}),
                ], style={"width": "380px", "maxWidth": "100%",
                          "background": SURFACE,
                          "border": f"1px solid {BORDER}",
                          "borderRadius": "36px", "padding": "22px",
                          "boxShadow": "0 12px 32px rgba(31, 41, 55, 0.12)",
                          "margin": "0 auto"}),
            ], style=CARD),
        ], id="patient-view", style={"display": "none"}),
    ], style={"flex": "1", "padding": "24px 28px 40px", "minWidth": "0"}),
], style={"display": "flex", "background": BG, "color": TEXT,
          "fontFamily": FONT, "minHeight": "100vh"})


@app.callback(
    [Output("view-store", "data"),
     Output("toggle-console", "style"),
     Output("toggle-patient", "style"),
     Output("nav-dashboard", "style"),
     Output("nav-patients", "style"),
     Output("nav-patientapp", "style")],
    [Input("toggle-console", "n_clicks"),
     Input("toggle-patient", "n_clicks"),
     Input("nav-dashboard", "n_clicks"),
     Input("nav-patients", "n_clicks"),
     Input("nav-patientapp", "n_clicks")])
def switch_view(_c, _p, _d, _pa, _pp):
    from dash import callback_context as ctx
    triggered = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered \
        else "toggle-console"
    view = "patient" if triggered in ("toggle-patient", "nav-patientapp") \
        else "console"
    # "Patients" opens the same console screen (the table is on it), so
    # only Dashboard carries the active state there.
    return (view, toggle_style(view == "console"),
            toggle_style(view == "patient"),
            NAV_BTN_ACTIVE if view == "console" else NAV_BTN,
            NAV_BTN,
            NAV_BTN_ACTIVE if view == "patient" else NAV_BTN)


@app.callback(
    [Output("console-view", "style"),
     Output("patient-view", "style")],
    [Input("view-store", "data")])
def show_view(view):
    if view == "patient":
        return {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}


@app.callback(
    [Output("patients-table", "data"),
     Output("table-order-store", "data")],
    [Input("patient-search", "value")])
def filter_patients(query):
    q = (query or "").strip().lower()
    if not q:
        return PATIENT_ROWS, [r["_id"] for r in PATIENT_ROWS]
    rows = [r for r in PATIENT_ROWS
            if q in r["Patient"].lower() or q in r["Plan"].lower()
            or q in r["Status"].lower()]
    return rows, [r["_id"] for r in rows]


@app.callback(
    Output("patient", "value"),
    [Input("patients-table", "active_cell")],
    [State("table-order-store", "data")])
def review_patient(cell, order):
    if not cell or not order:
        return "P002"
    row = cell.get("row", 0)
    if row is None or row >= len(order):
        return "P002"
    return order[row]


@app.callback(
    [Output("status-banner", "children"),
     Output("alerts", "children"),
     Output("trend", "figure"),
     Output("vomiting", "figure"),
     Output("weight", "figure"),
     Output("flags", "data"),
     Output("flags", "columns"),
     Output("raw-reports", "children"),
     Output("recent-checkins", "children")],
    [Input("patient", "value")])
def update(patient_id):
    patients, reports, events, changes = load(patient_id)
    patient = patients[patients["patient_id"] == patient_id]
    name = patient["name"].iloc[0]
    status, color = patient_status(events)
    vom_week = _vomiting_last_7d(events)

    worst = events[events["severity"].notna()]
    worst_txt = "—"
    if not worst.empty:
        row = worst.sort_values("severity", ascending=False).iloc[0]
        worst_txt = f"{row['symptom'].replace('_', ' ')} {int(row['severity'])}/10"

    flagged = events[(events["validation_flags"] != "") &
                     (events["validation_flags"] != "questionnaire_only")]

    banner = html.Div([
        html.Div([
            html.Span(status, style={"fontSize": "18px", "fontWeight": "700",
                                     "color": color}),
            html.Span(f"  {name}", style={"fontSize": "18px"}),
        ]),
        html.Div(f"Vomiting this week: {vom_week}   ·   "
                 f"Worst symptom: {worst_txt}   ·   "
                 f"Open flags: {len(flagged)}",
                 style={"marginTop": "6px", "fontFamily": MONO,
                        "fontSize": "13px", "color": MUTED}),
    ], style={"background": SURFACE, "border": f"1px solid {BORDER}",
              "borderLeft": f"5px solid {color}", "borderRadius": "16px",
              "padding": "16px 18px",
              "boxShadow": "0 1px 3px rgba(31, 41, 55, 0.06)"})

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
                style={"background": RED_BG, "border": "1px solid #fecaca",
                       "color": "#991b1b", "padding": "10px 14px",
                       "borderRadius": "8px"}))
    if vom_week >= 4:
        alerts.append(html.Div(
            f"⚠ Vomiting spike: {vom_week} episodes in the last 7 days.",
            style={"background": RED_BG, "border": "1px solid #fecaca",
                   "color": "#991b1b", "padding": "10px 14px",
                   "borderRadius": "8px", "marginTop": "6px"}))
    if not alerts:
        alerts = [html.Div("No active alerts.",
                           style={"color": GREEN})]

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
            html.Strong(str(r["reported_at"])[:10] + "  ",
                        style={"fontFamily": MONO, "fontSize": "13px"}),
            html.Span(r["free_text"] or "(questionnaire only)",
                      style={"fontStyle": "italic"}),
            html.Br(),
            html.Small("Parsed: " + (parsed or "—"),
                       style={"color": MUTED}),
        ], style={"borderBottom": f"1px solid {BORDER}",
                  "padding": "8px 0"}))

    checkins = []
    for _, r in reports.tail(4).iloc[::-1].iterrows():
        ev = events[events["report_id"] == r["report_id"]]
        bits = []
        for _, e in ev.iterrows():
            if e["symptom"] in ("nausea", "pain", "mouth_sores",
                                "swallowing") and pd.notna(e["severity"]):
                bits.append(f"{e['symptom'].replace('_', ' ')} "
                            f"{int(e['severity'])}/10")
            if e["symptom"] == "vomiting" \
                    and pd.notna(e["frequency_per_day"]) \
                    and int(e["frequency_per_day"]) > 0:
                bits.append(f"vomiting ×{int(e['frequency_per_day'])}")
            if e["symptom"] == "weight" and pd.notna(e["weight_kg"]):
                bits.append(f"{e['weight_kg']} kg")
        checkins.append(html.Div([
            html.Strong(str(r["reported_at"])[:10] + "  ",
                        style={"fontFamily": MONO, "fontSize": "13px"}),
            html.Span(" · ".join(bits) if bits else "No symptoms recorded",
                      style={"fontSize": "13px"}),
        ], style={"borderBottom": f"1px solid {BORDER}",
                  "padding": "8px 0"}))

    return (banner, alerts, trend_figure(events, changes),
            vomiting_figure(events), weight_figure(events, patient),
            flag_rows, columns, raw, checkins)


@app.callback(
    Output("phone-today", "children"),
    [Input("patient", "value")])
def phone_today(patient_id):
    patients, reports, events, _ = load(patient_id)
    patient = patients[patients["patient_id"] == patient_id]
    name = patient["name"].iloc[0].split()[0]
    last = reports.iloc[-1] if not reports.empty else None
    last_txt = pd.to_datetime(last["reported_at"]).strftime(
        "%A, %B %d, %Y") if last is not None else "No check-ins yet"
    status, _ = patient_status(events)
    latest = events.sort_values("reported_at")
    sev = latest[latest["severity"].notna()]
    today_bits = []
    if not sev.empty:
        row = sev.iloc[-1]
        today_bits.append(f"{row['symptom'].replace('_', ' ')} "
                          f"{int(row['severity'])}/10")
    vom = latest[latest["symptom"] == "vomiting"]
    if not vom.empty and pd.notna(vom.iloc[-1]["frequency_per_day"]) \
            and int(vom.iloc[-1]["frequency_per_day"]) > 0:
        today_bits.append(f"vomiting "
                          f"×{int(vom.iloc[-1]['frequency_per_day'])}")
    w = latest[(latest["symptom"] == "weight")
               & (latest["weight_kg"].notna())]
    if not w.empty:
        today_bits.append(f"weight {w.iloc[-1]['weight_kg']} kg")
    return [
        html.H2(f"Hi, {name}",
                style={"margin": "18px 0 2px", "fontSize": "24px"}),
        html.P(last_txt, style={"color": MUTED, "fontSize": "13px",
                                "margin": "0"}),
        html.Div([
            html.Span(status, style={"fontWeight": "700", "color": ACCENT}),
            html.Span(f"  ·  {len(reports)} check-ins logged",
                      style={"color": MUTED, "fontSize": "13px"}),
        ], style={"marginTop": "10px"}),
        html.Div([
            html.Div("Today's check-in",
                     style={"fontSize": "12px", "color": MUTED}),
            html.Div(" · ".join(today_bits) if today_bits else
                     "No symptoms recorded",
                     style={"fontSize": "14px", "marginTop": "4px"}),
        ], style={"background": PALE_TEAL, "borderRadius": "12px",
                  "padding": "12px 14px", "marginTop": "12px"}),
    ]


@app.callback(
    [Output("log-method-store", "data"),
     Output("log-method-rules", "style"),
     Output("log-method-llm", "style")],
    [Input("log-method-rules", "n_clicks"),
     Input("log-method-llm", "n_clicks")])
def set_log_method(_rules, _llm):
    from dash import callback_context as ctx
    triggered = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered \
        else "log-method-rules"
    method = "llm" if triggered == "log-method-llm" else "rules"
    return (method, toggle_style(method == "rules"),
            toggle_style(method == "llm"))


@app.callback(
    Output("log-results", "children"),
    [Input("log-save", "n_clicks")],
    [State("log-text", "value"),
     State("log-method-store", "data")])
def log_report(n_clicks, text, method):
    if not n_clicks:
        return ""
    if not (text or "").strip():
        # Never look dead: an empty save gets an answer, not silence.
        return html.Div("Type a report in the box first — for example: "
                        "“Threw up twice after dinner, felt nauseous all "
                        "morning.” Then press Save check-in.",
                        style={"fontSize": "13px", "color": AMBER,
                               "marginTop": "6px"})
    report = {"free_text": text.strip(), "questionnaire": {}}
    note = None
    used = "Rule-based parser"
    try:
        if method == "llm":
            from llm_client import gemini_extract
            events = parse_with_llm(report, gemini_extract)
            used = "LLM (Gemini) + validator"
        else:
            events = parse_report(report)
    except Exception as exc:
        events = parse_report(report)
        used = "Rule-based parser"
        note = f"LLM call failed ({exc}), so the rule-based parser ran " \
               "instead. Set GEMINI_API_KEY to use the LLM path."
    rows = []
    for e in events:
        bits = [e["symptom"].replace("_", " ")]
        if e.get("severity") is not None:
            bits.append(f"{e['severity']}/10")
        if e.get("frequency_per_day") is not None:
            bits.append(f"×{e['frequency_per_day']}/day")
        if e.get("timing"):
            bits.append(e["timing"])
        if e.get("weight_kg") is not None:
            bits.append(f"{e['weight_kg']} kg")
        flags = e.get("validation_flags") or "—"
        rows.append(html.Div([
            html.Strong(" · ".join(bits),
                        style={"fontSize": "13px"}),
            html.Span(f"   conf {e.get('confidence')} · {flags}",
                      style={"color": MUTED, "fontSize": "12px"}),
        ], style={"borderBottom": f"1px solid {BORDER}",
                  "padding": "7px 0"}))
    return [
        html.Div(f"Parsed with: {used}",
                 style={"fontSize": "12px", "color": MUTED}),
        html.Div(rows, style={"marginTop": "6px"}),
        html.Div(note, style={"fontSize": "12px", "color": AMBER,
                              "marginTop": "8px"}) if note else None,
    ]


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
