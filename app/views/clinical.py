import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from utils import (
    AXIS_STYLE,
    CATEGORICAL,
    PLOTLY_LAYOUT,
    RESULT_COLORS,
    fmt_count,
    fmt_pct,
    load_data,
    render_kpi_row,
    wrap_label,
)

data = load_data()
diagnoses = data["diagnoses"]
icd10_lookup = data["icd10_lookup"]
admissions = data["admissions"]
departments = data["departments"]
procedures = data["procedures"]
patient_procedures = data["patient_procedures"]
medications = data["medications"]
medical_tests = data["medical_tests"]

st.title("🩺 Clinical")

abnormal_rate = medical_tests["result"].fillna("").str.startswith("Abnormal").mean() * 100

render_kpi_row([
    ("Diagnoses recorded", fmt_count(len(diagnoses))),
    ("Procedures performed", fmt_count(len(patient_procedures))),
    ("Medications prescribed", fmt_count(len(medications))),
    ("Abnormal test rate", fmt_pct(abnormal_rate)),
])

st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("Top 10 diagnoses")
    dx = diagnoses.merge(icd10_lookup, on="icd10_code", how="left")
    dx["diagnosis_name"] = dx["diagnosis_name"].fillna(dx["icd10_code"])
    top_dx = dx["diagnosis_name"].value_counts().head(10).reset_index()
    top_dx.columns = ["diagnosis_name", "count"]
    top_dx = top_dx.sort_values("count")
    top_dx["diagnosis_label"] = top_dx["diagnosis_name"].apply(lambda t: wrap_label(t, width=30))
    fig = px.bar(top_dx, x="count", y="diagnosis_label", orientation="h")
    fig.update_traces(marker_color=CATEGORICAL[0])
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="", height=460)
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Diagnoses by department")
    dx_dept = (
        diagnoses.merge(admissions[["admission_id", "department_id"]], on="admission_id")
        .merge(departments[["department_id", "dep_name"]], on="department_id")
        .groupby("dep_name").size().rename("count").reset_index()
        .sort_values("count").tail(10)
    )
    fig = px.bar(dx_dept, x="count", y="dep_name", orientation="h")
    fig.update_traces(marker_color=CATEGORICAL[0])
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="", height=420)
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

col3, col4 = st.columns(2)

with col3:
    st.subheader("Top procedures performed")
    pp = patient_procedures.merge(procedures[["procedure_id", "procedure_name"]], on="procedure_id")
    top_proc = pp["procedure_name"].value_counts().head(10).reset_index()
    top_proc.columns = ["procedure_name", "count"]
    top_proc = top_proc.sort_values("count")
    fig = px.bar(top_proc, x="count", y="procedure_name", orientation="h")
    fig.update_traces(marker_color=CATEGORICAL[0])
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="", height=420)
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col4:
    st.subheader("Top medications prescribed")
    top_meds = medications["drug_name"].value_counts().head(10).reset_index()
    top_meds.columns = ["drug_name", "count"]
    top_meds = top_meds.sort_values("count")
    fig = px.bar(top_meds, x="count", y="drug_name", orientation="h")
    fig.update_traces(marker_color=CATEGORICAL[0])
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="", height=420)
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

col5, col6 = st.columns(2)

with col5:
    st.subheader("Medical test results")
    result_order = ["Normal", "Abnormal - Mild", "Abnormal - Moderate", "Abnormal - Severe", "Inconclusive", "Pending"]
    res = medical_tests["result"].fillna("Pending").value_counts().reindex(result_order, fill_value=0).reset_index()
    res.columns = ["result", "count"]
    res["result_label"] = res["result"].apply(lambda t: wrap_label(t, width=11))
    label_order = res.set_index("result").loc[result_order, "result_label"].tolist()
    fig = px.bar(
        res, x="result_label", y="count", color="result", color_discrete_map=RESULT_COLORS,
        category_orders={"result_label": label_order}, text="count",
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="")
    fig.update_xaxes(**AXIS_STYLE, tickangle=0)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col6:
    st.subheader("Tests by category")
    cat = medical_tests["test_category"].value_counts().reset_index()
    cat.columns = ["test_category", "count"]
    cat = cat.sort_values("count")
    fig = px.bar(cat, x="count", y="test_category", orientation="h")
    fig.update_traces(marker_color=CATEGORICAL[0])
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="", yaxis_title="")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)
