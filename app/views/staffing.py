import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import (
    AXIS_STYLE,
    CATEGORICAL,
    PLOTLY_LAYOUT,
    SHIFT_TYPE_COLORS,
    STAFF_TYPE_COLORS,
    fmt_count,
    load_data,
)

data = load_data()
doctors = data["doctors"]
nurses = data["nurses"]
employees = data["employees"]
departments = data["departments"]
staff_shifts = data["staff_shifts"]

st.title("👩‍⚕️ Staffing")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Doctors", fmt_count(len(doctors)))
k2.metric("Nurses", fmt_count(len(nurses)))
k3.metric("Employees", fmt_count(len(employees)))
k4.metric("Total shift-hours logged", fmt_count(staff_shifts["hours_worked"].sum()))

st.divider()

# ── Headcount by department (stacked, 3 identity series) ───────────────────
st.subheader("Headcount by department")
staff_frames = []
for df, staff_type, dept_col in [(doctors, "Doctor", "department_id"), (nurses, "Nurse", "department_id")]:
    t = df[[dept_col]].copy()
    t["staff_type"] = staff_type
    staff_frames.append(t.rename(columns={dept_col: "department_id"}))
emp_with_dept = employees.dropna(subset=["department_id"])[["department_id"]].copy()
emp_with_dept["staff_type"] = "Employee"
staff_frames.append(emp_with_dept)

staff_all = pd.concat(staff_frames, ignore_index=True).merge(
    departments[["department_id", "dep_name"]], on="department_id"
)
headcount = staff_all.groupby(["dep_name", "staff_type"]).size().rename("count").reset_index()
dept_order = (
    headcount.groupby("dep_name")["count"].sum().sort_values().index.tolist()
)
fig = px.bar(
    headcount, x="count", y="dep_name", color="staff_type", orientation="h",
    color_discrete_map=STAFF_TYPE_COLORS,
    category_orders={"dep_name": dept_order, "staff_type": ["Doctor", "Nurse", "Employee"]},
)
fig.update_layout(**PLOTLY_LAYOUT, xaxis_title="Headcount", yaxis_title="", height=560, barmode="stack")
fig.update_xaxes(**AXIS_STYLE)
fig.update_yaxes(**AXIS_STYLE)
st.plotly_chart(fig, use_container_width=True)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Doctor specialties (top 10)")
    spec = doctors["specialty"].value_counts().head(10).reset_index()
    spec.columns = ["specialty", "count"]
    spec = spec.sort_values("count")
    fig = px.bar(spec, x="count", y="specialty", orientation="h")
    fig.update_traces(marker_color=CATEGORICAL[0])
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="", height=420)
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Shift type distribution")
    shift_order = ["Morning", "Afternoon", "Night"]
    shifts = staff_shifts["shift_type"].value_counts().reindex(shift_order).reset_index()
    shifts.columns = ["shift_type", "count"]
    fig = px.bar(
        shifts, x="shift_type", y="count", color="shift_type",
        color_discrete_map=SHIFT_TYPE_COLORS, category_orders={"shift_type": shift_order},
        text="count",
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

col3, col4 = st.columns(2)

with col3:
    st.subheader("Shift-hours by staff type")
    hours = staff_shifts.groupby("staff_type")["hours_worked"].sum().reindex(["Doctor", "Nurse", "Employee"]).reset_index()
    fig = px.bar(
        hours, x="staff_type", y="hours_worked", color="staff_type",
        color_discrete_map=STAFF_TYPE_COLORS, text="hours_worked",
    )
    fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside", cliponaxis=False)
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="Total hours")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col4:
    st.subheader("Staff hires per year")
    hire_frames = []
    for df, staff_type in [(doctors, "Doctor"), (nurses, "Nurse"), (employees, "Employee")]:
        t = pd.DataFrame({"year": pd.to_datetime(df["hire_date"]).dt.year})
        t["staff_type"] = staff_type
        hire_frames.append(t)
    hires = pd.concat(hire_frames, ignore_index=True)
    hires_by_year = hires.groupby(["year", "staff_type"]).size().rename("count").reset_index()
    fig = px.line(
        hires_by_year, x="year", y="count", color="staff_type",
        color_discrete_map=STAFF_TYPE_COLORS,
        category_orders={"staff_type": ["Doctor", "Nurse", "Employee"]},
    )
    fig.update_traces(line=dict(width=2))
    fig.update_layout(**PLOTLY_LAYOUT, xaxis_title="", yaxis_title="New hires")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)
