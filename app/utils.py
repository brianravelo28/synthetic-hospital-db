"""
Shared data loading, formatting, and color-system helpers for the
Hospital Operations Dashboard.

Color system follows the validated reference palette (categorical order,
sequential ramp, status tokens) — see the dataviz skill's palette.md.
Colors are assigned by entity/job, never by chart-local rank, so the same
category always reads the same color across every page.
"""

from pathlib import Path

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

SHIFT_TYPE_COLORS = {
    "Morning": CATEGORICAL[3],
    "Afternoon": CATEGORICAL[1],
    "Night": CATEGORICAL[7],
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

PLOTLY_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color="#0b0b0b"),
    plot_bgcolor=CHART_SURFACE,
    paper_bgcolor=CHART_SURFACE,
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)

AXIS_STYLE = dict(gridcolor=GRID_HAIRLINE, linecolor="#c3c2b7", zeroline=False)

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
