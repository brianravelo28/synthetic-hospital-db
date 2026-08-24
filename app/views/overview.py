import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import (
    ADMISSION_TYPE_COLORS,
    AXIS_STYLE,
    CATEGORICAL,
    CONDITION_COLORS,
    CONDITION_ORDER,
    PLOTLY_LAYOUT,
    fmt_count,
    fmt_currency,
    load_data,
)

data = load_data()
admissions = data["admissions"]
departments = data["departments"]
patients = data["patients"]
billing = data["billing"]

st.title("🏥 Hospital Operations Overview")
st.caption(
    f"{len(patients):,} patients · {len(admissions):,} admissions · "
    f"data spans {admissions['admission_date'].min():%b %Y} – "
    f"{admissions['admission_date'].max():%b %Y}"
)

# ── KPI row ──────────────────────────────────────────────────────────────
discharged = admissions[admissions["admission_status"] == "Discharged"]
avg_los = discharged["length_of_stay"].mean()
total_revenue = billing["total_amount"].sum()
outstanding = billing["patient_responsibility"].where(
    billing["payment_status"].isin(["Pending", "Partial"]), 0
).sum()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Patients", fmt_count(len(patients)))
k2.metric("Admissions", fmt_count(len(admissions)))
k3.metric("Avg. length of stay", f"{avg_los:.1f} days")
k4.metric("Total billed", fmt_currency(total_revenue))
k5.metric("Outstanding balance", fmt_currency(outstanding))

st.divider()

col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("Admissions over time")
    monthly = (
        admissions.set_index("admission_date")
        .resample("MS")
        .size()
        .rename("admissions")
        .reset_index()
    )
    fig = px.line(monthly, x="admission_date", y="admissions")
    fig.update_traces(line=dict(color=CATEGORICAL[0], width=2))
    fig.update_layout(**PLOTLY_LAYOUT, xaxis_title="", yaxis_title="Admissions / month")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Admission type mix")
    mix = admissions["admission_type"].value_counts().reset_index()
    mix.columns = ["admission_type", "count"]
    mix = mix.sort_values("count")
    fig = px.bar(
        mix, x="count", y="admission_type", orientation="h",
        color="admission_type", color_discrete_map=ADMISSION_TYPE_COLORS,
        text="count",
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

col3, col4 = st.columns([3, 2])

with col3:
    st.subheader("Admission volume by department")
    dept_vol = (
        admissions.merge(departments, on="department_id")
        .groupby("dep_name")
        .size()
        .rename("admissions")
        .reset_index()
        .sort_values("admissions")
    )
    fig = px.bar(dept_vol, x="admissions", y="dep_name", orientation="h")
    fig.update_traces(marker_color=CATEGORICAL[0])
    fig.update_layout(
        **PLOTLY_LAYOUT, showlegend=False, xaxis_title="Admissions", yaxis_title="",
        height=520,
    )
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col4:
    st.subheader("Patient condition mix")
    st.caption("Ordered by acuity: Minimal → Intensive")
    cond = admissions["patient_condition"].value_counts().reindex(CONDITION_ORDER).reset_index()
    cond.columns = ["patient_condition", "count"]
    fig = px.bar(
        cond, x="count", y="patient_condition", orientation="h",
        color="patient_condition", color_discrete_map=CONDITION_COLORS,
        category_orders={"patient_condition": CONDITION_ORDER},
        text="count",
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)
