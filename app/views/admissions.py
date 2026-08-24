import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import (
    ADMISSION_STATUS_COLORS,
    AXIS_STYLE,
    CATEGORICAL,
    DISCHARGE_DISPOSITION_COLORS,
    PLOTLY_LAYOUT,
    SEQUENTIAL_BLUE,
    fmt_count,
    fmt_pct,
    load_data,
)

data = load_data()
admissions = data["admissions"]
departments = data["departments"]
triage = data["triage"]

st.title("🛏️ Admissions & Census")

# ── Filter row ───────────────────────────────────────────────────────────
min_date, max_date = admissions["admission_date"].min(), admissions["admission_date"].max()
f1, f2, f3 = st.columns([2, 2, 2])
with f1:
    date_range = st.date_input(
        "Admission date range", value=(min_date.date(), max_date.date()),
        min_value=min_date.date(), max_value=max_date.date(),
    )
with f2:
    dept_options = sorted(departments["dep_name"])
    dept_filter = st.multiselect("Department", dept_options, default=[])
with f3:
    type_options = sorted(admissions["admission_type"].unique())
    type_filter = st.multiselect("Admission type", type_options, default=[])

adm = admissions.merge(departments[["department_id", "dep_name"]], on="department_id")
if len(date_range) == 2:
    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1]) + pd.Timedelta(days=1)
    adm = adm[(adm["admission_date"] >= start) & (adm["admission_date"] < end)]
if dept_filter:
    adm = adm[adm["dep_name"].isin(dept_filter)]
if type_filter:
    adm = adm[adm["admission_type"].isin(type_filter)]

st.caption(f"{len(adm):,} admissions match the current filters")
st.divider()

# ── KPI row ──────────────────────────────────────────────────────────────
discharged = adm[adm["admission_status"] == "Discharged"]
cancelled_rate = (adm["admission_status"] == "Cancelled").mean() * 100 if len(adm) else 0
active_now = (adm["admission_status"] == "Admitted").sum()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Admissions", fmt_count(len(adm)))
k2.metric("Currently admitted", fmt_count(active_now))
k3.metric("Avg. length of stay", f"{discharged['length_of_stay'].mean():.1f} days" if len(discharged) else "—")
k4.metric("Cancellation rate", fmt_pct(cancelled_rate))

st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("Admission status")
    status_counts = adm["admission_status"].value_counts().reset_index()
    status_counts.columns = ["admission_status", "count"]
    status_order = ["Admitted", "Discharged", "Scheduled", "Cancelled"]
    status_counts["admission_status"] = pd.Categorical(status_counts["admission_status"], status_order)
    status_counts = status_counts.sort_values("admission_status")
    fig = px.bar(
        status_counts, x="admission_status", y="count",
        color="admission_status", color_discrete_map=ADMISSION_STATUS_COLORS,
        text="count",
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Length of stay distribution")
    st.caption("Discharged admissions only")
    if len(discharged):
        fig = px.histogram(discharged, x="length_of_stay", nbins=30)
        fig.update_traces(marker_color=CATEGORICAL[0])
        fig.update_layout(
            **PLOTLY_LAYOUT, showlegend=False,
            xaxis_title="Length of stay (days)", yaxis_title="Admissions",
        )
        fig.update_xaxes(**AXIS_STYLE)
        fig.update_yaxes(**AXIS_STYLE)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No discharged admissions in the current filter.")

col3, col4 = st.columns(2)

with col3:
    st.subheader("Discharge disposition")
    if len(discharged):
        disp = discharged["discharge_disposition"].value_counts().reset_index()
        disp.columns = ["discharge_disposition", "count"]
        disp = disp.sort_values("count")
        fig = px.bar(
            disp, x="count", y="discharge_disposition", orientation="h",
            color="discharge_disposition", color_discrete_map=DISCHARGE_DISPOSITION_COLORS,
            text="count",
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="")
        fig.update_xaxes(**AXIS_STYLE)
        fig.update_yaxes(**AXIS_STYLE)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No discharged admissions in the current filter.")

with col4:
    st.subheader("Triage acuity level")
    st.caption("ESI scale: 1 = most urgent, 5 = least urgent")
    adm_triage = triage[triage["admission_id"].isin(adm["admission_id"])]
    if len(adm_triage):
        acuity = adm_triage["acuity_level"].value_counts().reindex([1, 2, 3, 4, 5], fill_value=0).reset_index()
        acuity.columns = ["acuity_level", "count"]
        acuity["acuity_level"] = acuity["acuity_level"].astype(str)
        steps = [SEQUENTIAL_BLUE[12], SEQUENTIAL_BLUE[9], SEQUENTIAL_BLUE[6], SEQUENTIAL_BLUE[3], SEQUENTIAL_BLUE[1]]
        color_map = dict(zip(["1", "2", "3", "4", "5"], steps))
        fig = px.bar(
            acuity, x="acuity_level", y="count",
            color="acuity_level", color_discrete_map=color_map,
            text="count",
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="Acuity level", yaxis_title="")
        fig.update_xaxes(**AXIS_STYLE)
        fig.update_yaxes(**AXIS_STYLE)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No triage records in the current filter.")

st.subheader("Admissions by day of week")
dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
dow = adm["admission_date"].dt.day_name().value_counts().reindex(dow_order, fill_value=0).reset_index()
dow.columns = ["day", "count"]
fig = px.bar(dow, x="day", y="count", category_orders={"day": dow_order})
fig.update_traces(marker_color=CATEGORICAL[0])
fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="Admissions")
fig.update_xaxes(**AXIS_STYLE)
fig.update_yaxes(**AXIS_STYLE)
st.plotly_chart(fig, use_container_width=True)
