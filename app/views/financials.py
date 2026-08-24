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
    ITEM_TYPE_COLORS,
    PAYER_TYPE_COLORS,
    PAYMENT_STATUS_COLORS,
    PLOTLY_LAYOUT,
    fmt_currency,
    fmt_pct,
    load_data,
)

data = load_data()
billing = data["billing"]
billing_line_items = data["billing_line_items"]
payers = data["payers"]
admissions = data["admissions"]

st.title("💰 Financials")

total_billed = billing["total_amount"].sum()
total_covered = billing["insurance_covered"].sum()
total_patient_resp = billing["patient_responsibility"].sum()
paid_rate = (billing["payment_status"] == "Paid").mean() * 100

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total billed", fmt_currency(total_billed))
k2.metric("Insurance covered", fmt_currency(total_covered))
k3.metric("Patient responsibility", fmt_currency(total_patient_resp))
k4.metric("Bills fully paid", fmt_pct(paid_rate))

st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("Revenue by payer type")
    bill_payer = billing.merge(payers[["payer_id", "payer_type"]], on="payer_id")
    rev = bill_payer.groupby("payer_type")["total_amount"].sum().reset_index().sort_values("total_amount")
    fig = px.bar(
        rev, x="total_amount", y="payer_type", orientation="h",
        color="payer_type", color_discrete_map=PAYER_TYPE_COLORS,
    )
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="Total billed ($)", yaxis_title="")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Payment status mix")
    status_order = ["Paid", "Pending", "Partial", "Denied", "Write-Off"]
    status = billing["payment_status"].value_counts().reindex(status_order, fill_value=0).reset_index()
    status.columns = ["payment_status", "count"]
    fig = px.pie(
        status, names="payment_status", values="count", hole=0.55,
        color="payment_status", color_discrete_map=PAYMENT_STATUS_COLORS,
        category_orders={"payment_status": status_order},
    )
    fig.update_traces(textinfo="label+percent")
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

col3, col4 = st.columns(2)

with col3:
    st.subheader("Billing line items by type")
    items = billing_line_items.groupby("item_type")["total_cost"].sum().reset_index().sort_values("total_cost")
    fig = px.bar(
        items, x="total_cost", y="item_type", orientation="h",
        color="item_type", color_discrete_map=ITEM_TYPE_COLORS,
    )
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="Total cost ($)", yaxis_title="")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

with col4:
    st.subheader("Avg. bill amount by admission type")
    bill_type = billing.merge(admissions[["admission_id", "admission_type"]], on="admission_id")
    avg_by_type = bill_type.groupby("admission_type")["total_amount"].mean().reset_index().sort_values("total_amount")
    fig = px.bar(
        avg_by_type, x="total_amount", y="admission_type", orientation="h",
        color="admission_type", color_discrete_map=ADMISSION_TYPE_COLORS,
    )
    fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="Avg. total billed ($)", yaxis_title="")
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE)
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Billed revenue over time")
monthly_rev = (
    billing.set_index("bill_date").resample("MS")["total_amount"].sum().rename("revenue").reset_index()
)
fig = px.line(monthly_rev, x="bill_date", y="revenue")
fig.update_traces(line=dict(color=CATEGORICAL[0], width=2))
fig.update_layout(**PLOTLY_LAYOUT, xaxis_title="", yaxis_title="Billed revenue ($) / month")
fig.update_xaxes(**AXIS_STYLE)
fig.update_yaxes(**AXIS_STYLE)
st.plotly_chart(fig, use_container_width=True)
