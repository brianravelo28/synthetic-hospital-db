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
    daily_census,
    fmt_count,
    fmt_pct,
    inpatient_beds,
    load_data,
    load_validation,
    OCCUPANCY_WARMUP_DAYS,
    plot,
    render_kpi_row,
)

data = load_data()
admissions = data["admissions"]
departments = data["departments"]
triage = data["triage"]
rooms = data["rooms"]
as_of = pd.Timestamp(load_validation()["meta"].get("as_of") or admissions["discharge_date"].max())

st.title("🛏️ Admissions & Census")

# KPI row is reserved here (top, right after the title) so its position
# stays stable across every page — filled in below, after the filters,
# once the filtered values it depends on are known.
kpi_slot = st.container()

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

# ── KPI row (rendered into the slot reserved above) ─────────────────────
discharged = adm[adm["admission_status"] == "Discharged"]
cancelled_rate = (adm["admission_status"] == "Cancelled").mean() * 100 if len(adm) else 0
active_now = (adm["admission_status"] == "Admitted").sum()

with kpi_slot:
    render_kpi_row([
        ("Admissions", fmt_count(len(adm))),
        ("Currently admitted", fmt_count(active_now)),
        ("Avg. length of stay", f"{discharged['length_of_stay'].mean():.1f} days" if len(discharged) else "—"),
        ("Cancellation rate", fmt_pct(cancelled_rate)),
    ])

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
    plot(fig)

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
        plot(fig)
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
        plot(fig)
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
        plot(fig)
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
plot(fig)

# ── Occupancy ───────────────────────────────────────────────────────────
st.divider()
st.subheader("Occupancy")
st.caption(
    "**Census** is the number of patients in an inpatient bed at midnight. **Bed occupancy** is census divided by "
    "inpatient beds (Standard, Private, ICU, NICU and Isolation rooms; OR, ER and Recovery rooms are procedure and "
    f"visit spaces, not beds). The first {OCCUPANCY_WARMUP_DAYS} days are left out because the hospital starts empty. "
    "Follows the department and date filters above; the admission-type filter does not apply."
)

selected_ids = departments.loc[departments["dep_name"].isin(dept_filter), "department_id"] if dept_filter else departments["department_id"]
occ_rooms = rooms[rooms["department_id"].isin(selected_ids)]
occ_adm = admissions[admissions["department_id"].isin(selected_ids)]
census = daily_census(occ_adm, occ_rooms, as_of)
beds = inpatient_beds(occ_rooms)
if len(census) and beds.sum():
    census = census[census.index >= census.index.min() + pd.Timedelta(days=OCCUPANCY_WARMUP_DAYS)]
    if len(date_range) == 2:
        census = census[(census.index >= pd.Timestamp(date_range[0])) & (census.index <= pd.Timestamp(date_range[1]))]
if len(census) and beds.sum():
    total = census.sum(axis=1)
    render_kpi_row([
        ("Average daily census", f"{total.mean():.0f}"),
        ("Inpatient beds", fmt_count(beds.sum())),
        ("Average bed occupancy", fmt_pct(total.mean() / beds.sum() * 100)),
        ("Busiest day", fmt_pct(total.max() / beds.sum() * 100)),
    ])
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Daily census")
        day = total.rename("Patients in a bed").reset_index().rename(columns={"index": "Day"})
        fig = px.line(day, x="Day", y="Patients in a bed")
        fig.update_traces(line=dict(color=CATEGORICAL[0], width=2))
        fig.add_hline(y=beds.sum(), line_dash="dash", line_color="#898781",
                      annotation_text=f"{int(beds.sum())} inpatient beds", annotation_position="top left",
                      annotation_font_size=13)
        fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="Patients in a bed")
        fig.update_xaxes(**AXIS_STYLE)
        fig.update_yaxes(**AXIS_STYLE, rangemode="tozero")
        plot(fig)
    with c2:
        st.subheader("Occupancy by room type")
        present = [t for t in census.columns if beds.get(t, 0) > 0]
        by_type = pd.DataFrame({
            "Room type": present * 2,
            "Measure": ["Average"] * len(present) + ["Busiest day"] * len(present),
            "Occupancy (%)": [round(census[t].mean() / beds[t] * 100, 1) for t in present]
                             + [round(census[t].max() / beds[t] * 100, 1) for t in present],
        })
        fig = px.bar(by_type, x="Room type", y="Occupancy (%)", color="Measure", barmode="group", text="Occupancy (%)",
                     color_discrete_map={"Average": CATEGORICAL[0], "Busiest day": CATEGORICAL[1]},
                     category_orders={"Room type": present, "Measure": ["Average", "Busiest day"]})
        fig.update_traces(textposition="outside", cliponaxis=False, texttemplate="%{text:.0f}%")
        fig.update_layout(**PLOTLY_LAYOUT, xaxis_title="", yaxis_title="Occupancy (%)", legend_title_text="")
        fig.update_xaxes(**AXIS_STYLE)
        fig.update_yaxes(**AXIS_STYLE, range=[0, 115])
        plot(fig)
else:
    st.info("No inpatient stays in the current department and date selection.")
