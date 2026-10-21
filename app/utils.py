"""
Shared data loading, formatting, and color-system helpers for the
Hospital Operations Dashboard.

Color system follows the validated reference palette (categorical order,
sequential ramp, status tokens) — see the dataviz skill's palette.md.
Colors are assigned by entity/job, never by chart-local rank, so the same
category always reads the same color across every page.
"""

import json
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).parent / "data"

# ── Color system (validated reference palette — light mode) ────────────────

CATEGORICAL = [
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#4a3aa7",  # 7 violet
    "#e34948",  # 8 red
]

SEQUENTIAL_BLUE = [  # step 100 -> 700, light -> dark
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec",
    "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab",
    "#184f95", "#104281", "#0d366b",
]

STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
    "neutral": "#898781",  # muted gray, for non-evaluative "pending/unknown" states
}

INK_SECONDARY = "#52514e"
GRID_HAIRLINE = "#e1e0d9"
CHART_SURFACE = "#fcfcfb"

# Fixed identity color maps — one entry per category value, assigned once
# so filtering never repaints a survivor with a new color.
ADMISSION_TYPE_COLORS = {
    "Emergency": CATEGORICAL[0],
    "Elective": CATEGORICAL[1],
    "Urgent": CATEGORICAL[2],
    "Newborn": CATEGORICAL[3],
    "Scheduled": CATEGORICAL[4],
}

ADMISSION_STATUS_COLORS = {
    "Admitted": CATEGORICAL[0],
    "Discharged": CATEGORICAL[2],
    "Scheduled": CATEGORICAL[3],
    "Cancelled": CATEGORICAL[7],
}

GENDER_COLORS = {"M": CATEGORICAL[0], "F": CATEGORICAL[4], "NB": CATEGORICAL[6]}

PAYER_TYPE_COLORS = {
    "Medicare": CATEGORICAL[0],
    "Medicaid": CATEGORICAL[1],
    "Private Insurance": CATEGORICAL[2],
    "Self-Pay": CATEGORICAL[3],
    "Workers Compensation": CATEGORICAL[4],
    "CHIP": CATEGORICAL[5],
}

ITEM_TYPE_COLORS = {
    "Procedure": CATEGORICAL[0],
    "Medication": CATEGORICAL[1],
    "Room": CATEGORICAL[2],
    "Lab": CATEGORICAL[3],
    "Consultation": CATEGORICAL[4],
}

PAYMENT_STATUS_COLORS = {
    "Paid": CATEGORICAL[0],
    "Pending": CATEGORICAL[1],
    "Partial": CATEGORICAL[2],
    "Denied": CATEGORICAL[3],
    "Write-Off": CATEGORICAL[4],
}

STAFF_TYPE_COLORS = {
    "Doctor": CATEGORICAL[0],
    "Nurse": CATEGORICAL[2],
    "Employee": CATEGORICAL[6],
}

# slots 4/1/7, not 4/2/8: orange and red were only dE 7 apart (palette validator)
SHIFT_TYPE_COLORS = {
    "Morning": CATEGORICAL[3],
    "Afternoon": CATEGORICAL[0],
    "Night": CATEGORICAL[6],
}

# patient_condition is an ORDERED severity scale -> ordinal ramp, not identity
CONDITION_ORDER = ["Minimal", "Moderate", "Maximum", "Intensive"]
CONDITION_COLORS = dict(zip(CONDITION_ORDER, [SEQUENTIAL_BLUE[3], SEQUENTIAL_BLUE[6], SEQUENTIAL_BLUE[8], SEQUENTIAL_BLUE[11]]))

# discharge_disposition mixes genuinely evaluative outcomes (status tokens)
# with neutral care-transition types (categorical slots)
DISCHARGE_DISPOSITION_COLORS = {
    "Home": STATUS["good"],
    "Deceased": STATUS["critical"],
    "AMA": STATUS["warning"],
    "Transfer": CATEGORICAL[2],
    "Skilled Nursing Facility": CATEGORICAL[6],
}

# result severity is ordered and evaluative -> status tokens
RESULT_COLORS = {
    "Normal": STATUS["good"],
    "Abnormal - Mild": STATUS["warning"],
    "Abnormal - Moderate": STATUS["serious"],
    "Abnormal - Severe": STATUS["critical"],
    "Inconclusive": STATUS["neutral"],
    "Pending": STATUS["neutral"],
}

# Dashboard-wide minimum font size (px). Nothing — chart chrome included —
# should render smaller than this.
MIN_FONT_SIZE = 13

PLOTLY_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color="#0b0b0b", size=MIN_FONT_SIZE),
    plot_bgcolor=CHART_SURFACE,
    paper_bgcolor=CHART_SURFACE,
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=MIN_FONT_SIZE)),
)

AXIS_STYLE = dict(
    gridcolor=GRID_HAIRLINE, linecolor="#c3c2b7", zeroline=False,
    tickfont=dict(size=MIN_FONT_SIZE), title_font=dict(size=MIN_FONT_SIZE),
)

# Injected once from app.py — Streamlit's own chrome (captions, metric
# labels, widget labels, etc.) can render below MIN_FONT_SIZE by default.
BASE_CSS = f"""
<style>
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] span,
.stCaption,
small,
[data-testid="stMetricLabel"],
[data-testid="stMetricDelta"],
[data-testid="stWidgetLabel"] p,
[data-testid="stMarkdownContainer"] p {{
    font-size: {MIN_FONT_SIZE}px !important;
}}

.kpi-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    margin: 4px 0 28px 0;
}}
.kpi-card {{
    flex: 1 1 180px;
    background: {CHART_SURFACE};
    border: 1px solid {GRID_HAIRLINE};
    border-radius: 12px;
    padding: 18px 22px;
    box-shadow: 0 1px 2px rgba(11, 11, 11, 0.04);
}}
.kpi-label {{
    font-size: 15px;
    font-weight: 600;
    color: {INK_SECONDARY};
    margin-bottom: 8px;
}}
.kpi-value {{
    font-size: 34px;
    font-weight: 700;
    color: #0b0b0b;
    line-height: 1.15;
    white-space: nowrap;
}}
</style>
"""

# ── Date columns to parse per table ─────────────────────────────────────────

_DATE_COLUMNS = {
    "patients": ["birth_date", "registered_date"],
    "doctors": ["birth_date", "hire_date"],
    "nurses": ["birth_date", "hire_date"],
    "employees": ["hire_date"],
    "admissions": ["admission_date", "discharge_date"],
    "triage": ["triage_datetime"],
    "diagnoses": ["diagnosis_date"],
    "patient_procedures": ["procedure_date"],
    "medications": ["start_date", "end_date"],
    "medical_tests": ["test_date", "result_date"],
    "staff_shifts": ["shift_date"],
    "billing": ["bill_date", "due_date", "payment_date"],
}

_TABLES = [
    "departments", "payers", "procedures", "patients", "doctors", "nurses",
    "employees", "rooms", "admissions", "triage", "diagnoses",
    "patient_procedures", "medications", "medical_tests", "staff_shifts",
    "billing", "billing_line_items", "icd10_lookup",
]


@st.cache_data
def load_data() -> dict:
    """Load every source CSV once per session, with date columns parsed."""
    data = {}
    for table in _TABLES:
        df = pd.read_csv(DATA_DIR / f"{table}.csv")
        for col in _DATE_COLUMNS.get(table, []):
            df[col] = pd.to_datetime(df[col], errors="coerce")
        data[table] = df
    return data


@st.cache_data
def load_validation() -> dict:
    """Validation outputs written by src/run_pipeline.py (see the Data Quality page)."""
    with open(DATA_DIR / "validation_report_meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    return {
        "report": pd.read_csv(DATA_DIR / "validation_report.csv"),
        "meta": meta,
        "runs": pd.read_csv(DATA_DIR / "validation_runs.csv"),
        "baseline": pd.read_csv(DATA_DIR / "validation_baseline_pre_fix.csv"),
        "baseline_clinical": pd.read_csv(DATA_DIR / "validation_baseline_pre_coherence.csv"),
    }


# ── Occupancy ───────────────────────────────────────────────────────────────
# Inpatient beds exclude OR, ER and Recovery rooms (procedure and visit spaces).
INPATIENT_ROOM_TYPES = ["Standard", "Private", "ICU", "NICU", "Isolation"]
OCCUPANCY_WARMUP_DAYS = 45      # the hospital starts empty, so the first stretch is left out of averages


def daily_census(admissions: pd.DataFrame, rooms: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """
    Patients in an inpatient bed at midnight, by room type: one row per day, one column
    per inpatient room type. A stay is counted on every midnight from its admission up to
    (not including) the midnight on or after it ends; a stay still under way lasts to as_of.
    """
    stays = admissions[admissions["admission_status"].isin(["Admitted", "Discharged"]) & admissions["room_id"].notna()]
    stays = stays.merge(rooms[["room_id", "room_type"]], on="room_id")
    stays = stays[stays["room_type"].isin(INPATIENT_ROOM_TYPES)]
    if stays.empty:
        return pd.DataFrame(columns=INPATIENT_ROOM_TYPES, dtype=float)
    first = stays["admission_date"].min().normalize()
    days = pd.date_range(first, pd.Timestamp(as_of).normalize(), freq="D")
    one_day = pd.Timedelta(days=1)
    start = np.ceil(((stays["admission_date"] - first) / one_day).to_numpy()).astype(int)
    end = np.ceil(((stays["discharge_date"].fillna(pd.Timestamp(as_of)) - first) / one_day).to_numpy()).astype(int)
    out = {}
    for room_type in INPATIENT_ROOM_TYPES:
        pick = (stays["room_type"] == room_type).to_numpy()
        change = np.zeros(len(days) + 1)
        np.add.at(change, np.clip(start[pick], 0, len(days)), 1)
        np.add.at(change, np.clip(end[pick], 0, len(days)), -1)
        out[room_type] = np.cumsum(change)[: len(days)]
    return pd.DataFrame(out, index=days)


def inpatient_beds(rooms: pd.DataFrame) -> pd.Series:
    """Beds by inpatient room type."""
    inpatient = rooms[rooms["room_type"].isin(INPATIENT_ROOM_TYPES)]
    return inpatient.groupby("room_type")["bed_capacity"].sum().reindex(INPATIENT_ROOM_TYPES).fillna(0)


# ── Formatting helpers ──────────────────────────────────────────────────────

def fmt_currency(x: float) -> str:
    if pd.isna(x):
        return "—"
    if abs(x) >= 1_000_000:
        return f"${x / 1_000_000:,.1f}M"
    if abs(x) >= 1_000:
        return f"${x / 1_000:,.0f}K"
    return f"${x:,.0f}"


def fmt_count(x: float) -> str:
    if pd.isna(x):
        return "—"
    return f"{x:,.0f}"


def fmt_pct(x: float) -> str:
    if pd.isna(x):
        return "—"
    return f"{x:.1f}%"


def wrap_label(text: str, width: int = 25, max_lines: int = 2) -> str:
    """
    Wrap a long chart-axis label onto at most `max_lines` lines (joined with
    <br>, which Plotly renders as a line break) instead of shrinking the font
    or letting it run off the chart. Excess beyond max_lines is ellipsized.
    """
    lines = textwrap.wrap(text, width=width, break_long_words=False)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…"
    return "<br>".join(lines)


CHART_HINT = "Drag to zoom · double-click to reset"


def chart_table(fig) -> pd.DataFrame | None:
    """The numbers behind a Plotly figure as a table, read from the figure itself
    so the chart and its table view cannot disagree. Returns None if the figure
    has nothing tabulable. Histograms (raw values, binned by the browser) get
    summary statistics instead of bins we would have to guess."""
    traces = [t for t in fig.data if t.type in ("bar", "scatter", "pie", "histogram")]
    if not traces:
        return None
    layout = fig.layout

    def axis_title(axis, default):
        text = axis.title.text if axis is not None and axis.title is not None else None
        return text or default

    if traces[0].type == "histogram":
        x = pd.Series(list(traces[0].x), dtype="float64")
        label = axis_title(layout.xaxis, "Value")
        return pd.DataFrame({label: {
            "Count": f"{len(x):,}", "Min": f"{x.min():,.1f}", "Median": f"{x.median():,.1f}",
            "Mean": f"{x.mean():,.1f}", "90th percentile": f"{x.quantile(0.9):,.1f}", "Max": f"{x.max():,.1f}",
        }}).rename_axis("Statistic").reset_index()

    if traces[0].type == "pie":
        t = traces[0]
        return pd.DataFrame({"Category": list(t.labels), "Value": list(t.values)})

    horizontal = traces[0].orientation == "h"
    cat_title = axis_title(layout.yaxis if horizontal else layout.xaxis, "Category")
    val_title = axis_title(layout.xaxis if horizontal else layout.yaxis, "Value")
    frames = []
    for t in traces:
        cats, vals = (t.y, t.x) if horizontal else (t.x, t.y)
        if cats is None or vals is None:
            continue
        frames.append(pd.DataFrame({cat_title: list(cats), "series": t.name or val_title, val_title: list(vals)}))
    if not frames:
        return None
    long = pd.concat(frames, ignore_index=True)
    if long.groupby(cat_title)["series"].nunique().max() == 1:
        # one series, or colour just repeats the category (one bar per trace): no pivot needed
        return long.drop(columns="series")
    order = list(dict.fromkeys(long[cat_title]))                  # keep the chart's own order
    wide = long.pivot_table(index=cat_title, columns="series", values=val_title, aggfunc="sum")
    series_order = list(dict.fromkeys(long["series"]))
    return wide.reindex(order)[series_order].reset_index()


def plot(fig, hint: bool = True) -> None:
    """Render a Plotly figure with the standing drag-to-zoom / double-click-to-reset
    hint underneath (pass hint=False for charts that can't zoom, e.g. donuts),
    plus a collapsed "View as table" twin so no value depends on colour or hover."""
    st.plotly_chart(fig, width="stretch")
    if hint:
        st.caption(CHART_HINT)
    table = chart_table(fig)
    if table is not None:
        with st.expander("View as table"):
            st.dataframe(table, hide_index=True, width="stretch")


def render_kpi_row(items: list) -> None:
    """
    Render a row of styled stat-tile cards (label + large value each),
    instead of Streamlit's plain st.metric row — see the .kpi-row/.kpi-card
    rules in BASE_CSS. `items` is a list of (label, value) string pairs.
    """
    cards = "".join(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div></div>'
        for label, value in items
    )
    st.markdown(f'<div class="kpi-row">{cards}</div>', unsafe_allow_html=True)
