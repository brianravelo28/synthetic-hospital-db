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
    STATUS,
    fmt_count,
    load_validation,
    plot,
    render_kpi_row,
)

RULE_DESCRIPTIONS = {
    # Group 1 — temporal
    "discharge_before_admission": "Discharge date is earlier than the admission date",
    "los_inconsistent": "Stored length of stay doesn't match discharge minus admission",
    "triage_out_of_window": "Triage recorded outside the admission window",
    "diagnosis_out_of_window": "Diagnosis dated outside the admission window",
    "procedure_out_of_window": "Procedure dated outside the admission window",
    "medication_date_issues": "Medication starts before admission, ends before it starts, or runs past discharge",
    "test_out_of_window": "Test dated outside the admission window",
    "result_before_test": "Test result dated before the test itself",
    "bill_before_discharge": "Bill dated before the patient was discharged",
    "payment_before_bill": "Payment dated before the bill",
    # Group 2 — age
    "newborn_wrong_age": "'Newborn' admission for a patient older than 0",
    "newborn_wrong_dept": "'Newborn' admission outside Pediatrics / OB-GYN",
    "newborn_wrong_registered_date": "A newborn's registration date isn't their admission date",
    "pediatric_in_geriatric_dept": "Child (1–17) admitted to Geriatric",
    "adult_in_pediatric_dept": "Adult admitted to Pediatrics",
    "geriatric_newborn_diagnosis": "Newborn-only diagnosis code on a patient older than 1",
    # Group 3 — admission type
    "emergency_low_acuity": "Emergency admission with a low-urgency (ESI 4–5) triage",
    "scheduled_has_triage": "A scheduled (future) admission already has triage records",
    "scheduled_has_diagnoses": "A scheduled admission already has diagnoses",
    "scheduled_has_procedures": "A scheduled admission already has procedures",
    "scheduled_has_medications": "A scheduled admission already has medications",
    "scheduled_has_tests": "A scheduled admission already has tests",
    "scheduled_has_billing": "A scheduled or cancelled admission has a bill",
    "scheduled_has_room": "A scheduled admission already has a room",
    # Group 4 — department
    "doctor_dept_mismatch": "Admitting doctor works in a different department (cross-department specialties excepted)",
    "room_dept_mismatch": "Room belongs to a different department than the admission",
    "condition_room_mismatch": "Room type doesn't suit the patient's condition (e.g. 'Intensive' in a standard room)",
    # Group 5 — diagnoses
    "male_impossible_codes": "Pregnancy or breast-cancer code on a male patient",
    "female_impossible_codes": "Prostate-cancer code on a female patient",
    "newborn_codes_on_adults": "Newborn-only code on a patient older than 1",
    # Group 6 — financial
    "billing_amount_mismatch": "Bill total doesn't equal the sum of its line items",
    "denied_with_coverage": "A denied bill still shows insurance coverage",
    "writeoff_with_patient_resp": "A written-off bill still charges the patient",
    "paid_missing_payment_date": "A paid bill has no payment date",
    "unpaid_has_payment_date": "A pending / denied / written-off bill has a payment date",
    # Group 7 — operational realism
    "census_exceeds_bed_capacity": "More patients currently admitted in a department than it has beds",
    "stale_admitted_over_60d": "Patient still 'admitted' 60+ days after admission",
    "scheduled_in_past": "A 'scheduled' admission dated in the past",
    "admission_before_birth": "Admission dated before the patient was born",
    "registered_before_birth": "Patient registered before they were born",
    "registered_in_future": "Patient registration date is in the future",
    "bill_before_admission": "Bill dated before the admission began",
    "bill_on_undischarged_admission": "Bill issued for a patient who hasn't been discharged",
    "procedure_item_wrong_admission": "Billed procedure belongs to a different admission",
    "lab_item_wrong_admission": "Billed lab test belongs to a different admission",
    "procedure_or_lab_item_missing_link": "Procedure / lab line item with no procedure / test attached",
    "cancelled_has_clinical_records": "A cancelled admission has triage, diagnoses, procedures, medications or tests",
    "pediatric_vitals_implausible": "Infant or child with adult height / weight at triage",
    "staff_hired_before_age_21": "Doctor or nurse hired before turning 21",
    "staff_event_before_hire": "Doctor or nurse recorded acting before their hire date",
    "shift_before_hire_or_wrong_dept": "Shift before the staff member's hire date, or outside their own department",
    # Group 8 — clinical coherence
    "delivery_wrong_patient": "A delivery procedure on a patient who is not female or not of childbearing age (12-55)",
    "delivery_without_obstetric_dx": "A delivery procedure on an admission with no obstetric diagnosis",
    "adult_surgery_on_minor": "Bypass surgery, hip/knee replacement or hip-fracture fixation on a patient under 18",
    "cancer_treatment_without_cancer_dx": "Chemotherapy or radiation on an admission with no cancer diagnosis",
    "diabetes_drug_without_diabetes_dx": "Insulin or metformin on an admission with no diabetes diagnosis",
    "pap_smear_wrong_patient": "A Pap smear on a patient who is not female or is under 21",
}

GROUP_SHORT = {
    "group1_temporal": "1 · Temporal",
    "group2_age": "2 · Age-based",
    "group3_admission_type": "3 · Admission type",
    "group4_department": "4 · Department",
    "group5_diagnoses": "5 · Diagnoses",
    "group6_financial": "6 · Financial",
    "group7_realism": "7 · Realism (detect-only)",
    "group8_clinical": "8 · Clinical coherence (detect-only)",
}

GRAY = "#b9b8b0"   # de-emphasis tone for the "before" bars

val = load_validation()
report, meta, runs, baseline = val["report"], val["meta"], val["runs"], val["baseline"]
baseline_clinical = val["baseline_clinical"]

report["group_short"] = report["group"].map(GROUP_SHORT)
report["what"] = report["rule"].map(RULE_DESCRIPTIONS).fillna("")

st.title("🧪 Data Quality")
st.caption(
    f"{len(report)} automated checks in 8 groups, run after every generation. "
    f"Showing the latest run: **{meta['size']}** scale, {fmt_count(meta['admissions'])} admissions."
)

passing = int((report["after_repair"] == 0).sum())
render_kpi_row([
    ("Checks run", fmt_count(len(report))),
    ("Passing after repair", f"{passing} of {len(report)}"),
    ("Violations before repair", fmt_count(report["before_repair"].sum())),
    ("Violations after repair", fmt_count(report["after_repair"].sum())),
])

st.markdown(
    "The generator is built to avoid violations in the first place; a repair step then fixes whatever "
    "slips through. **Before repair** is what the generator itself produced; **after repair** is what "
    "is left in the dataset behind this dashboard. Groups 1–6 were written alongside the generator. "
    "**Groups 7 and 8 were added afterwards and deliberately not designed around** — they only report, "
    "because repairing e.g. a bill line that points at the wrong patient's procedure would mean "
    "inventing data."
)
st.divider()

# ── Before vs after, by group ────────────────────────────────────────────
st.subheader("Violations by group, before vs after repair")
by_group = (
    report.groupby(["group", "group_short"], sort=False)[["before_repair", "after_repair"]].sum().reset_index()
)
long = by_group.melt(
    id_vars=["group", "group_short"], value_vars=["before_repair", "after_repair"],
    var_name="stage", value_name="violations",
)
long["stage"] = long["stage"].map({"before_repair": "Before repair", "after_repair": "After repair"})
fig = px.bar(
    long, x="violations", y="group_short", color="stage", orientation="h", barmode="group",
    color_discrete_map={"Before repair": GRAY, "After repair": CATEGORICAL[0]},
    category_orders={"stage": ["Before repair", "After repair"],
                     "group_short": list(GROUP_SHORT.values())[::-1]},
)
fig.update_layout(**PLOTLY_LAYOUT, xaxis_title="Violations", yaxis_title="", height=420, legend_title_text="")
fig.update_xaxes(**AXIS_STYLE)
fig.update_yaxes(**AXIS_STYLE)
plot(fig)
leftover = report[report["after_repair"] > 0]
note = "A group with no bar has zero violations."
if (leftover["rule"] == "condition_room_mismatch").any():
    note += (" What remains after repair is the room-type scarcity case: a department with no room "
             "suited to a patient's condition (repair downgrades the recorded condition rather than "
             "invent a room).")
st.caption(note)

# ── By scale ─────────────────────────────────────────────────────────────
st.subheader("Results at each scale")
runs_view = runs.assign(
    admissions=runs["admissions"].map("{:,}".format),
    violations_before_repair=runs["violations_before_repair"].map("{:,}".format),
    violations_after_repair=runs["violations_after_repair"].map("{:,}".format),
).rename(columns={
    "size": "Scale", "admissions": "Admissions", "checks": "Checks",
    "violations_before_repair": "Before repair", "violations_after_repair": "After repair",
    "generated_at_utc": "Run (UTC)",
})
st.dataframe(runs_view, hide_index=True, width="stretch")
st.caption("Each row is the most recent recorded run at that scale; exact counts shift by a few between regenerations.")

st.divider()

# ── The independent checks vs the pre-fix data ──────────────────────────
st.subheader("What the independent checks found before the fixes")
old_12_6 = int(baseline.loc[baseline["group"] != "group7_realism", "count"].sum())
old_7 = baseline[baseline["group"] == "group7_realism"].copy()
st.markdown(
    f"Run against the dataset produced by the generator **before** these fixes, checks 1–6 reported "
    f"only **{old_12_6}** violations — the generator had been built to satisfy exactly those rules. "
    f"The 16 realism checks, added afterwards, found **{fmt_count(old_7['count'].sum())}**: a dashboard "
    f"showing 2,409 patients 'currently admitted' (one admitted in 2020), line items pointing at "
    f"other patients' procedures, doctors treating before they were hired. Each one was then fixed "
    f"in the generator, and the same checks now pass on fresh data."
)
old_7["what"] = old_7["rule"].map(RULE_DESCRIPTIONS)
old_7 = old_7[old_7["count"] > 0].sort_values("count")
fig = px.bar(old_7, x="count", y="rule", orientation="h", text="count")
fig.update_traces(marker_color=STATUS["serious"], texttemplate="%{text:,}", textposition="outside", cliponaxis=False)
fig.update_layout(**PLOTLY_LAYOUT, showlegend=False, xaxis_title="Violations in the pre-fix dataset",
                  yaxis_title="", height=520)
fig.update_xaxes(**AXIS_STYLE)
fig.update_yaxes(**AXIS_STYLE)
plot(fig)

st.divider()

# ── Clinical coherence: before / after the diagnosis-linked generator ────
st.subheader("Do the treatments fit the patient and the diagnosis?")
clin = baseline_clinical.rename(columns={"count": "before"}).merge(
    report[["rule", "before_repair"]].rename(columns={"before_repair": "now"}), on="rule", how="left"
)
st.markdown(
    f"Procedures, medications and tests used to be drawn at random, independent of each other and of "
    f"the patient. Six hard contradictions (a delivery on a male patient, chemotherapy with no cancer "
    f"diagnosis, insulin with no diabetes) showed up **{fmt_count(clin['before'].sum())}** times in the "
    f"earlier large dataset. The generator now chooses treatments from each admission's own diagnoses "
    f"and the patient's sex and age; the same six checks find **{fmt_count(clin['now'].sum())}** now. "
    f"The checks are written from CPT codes and drug names, separately from the generator's mapping."
)
cl = clin.melt(id_vars="rule", value_vars=["before", "now"], var_name="stage", value_name="violations")
cl["stage"] = cl["stage"].map({"before": "Earlier generator", "now": "Current generator"})
order = clin.sort_values("before")["rule"].tolist()
fig = px.bar(
    cl, x="violations", y="rule", color="stage", orientation="h", barmode="group",
    color_discrete_map={"Earlier generator": GRAY, "Current generator": CATEGORICAL[0]},
    category_orders={"stage": ["Earlier generator", "Current generator"], "rule": order},
)
fig.update_traces(texttemplate="%{x:,}", textposition="outside", cliponaxis=False)   # label the zeros too
fig.update_layout(**PLOTLY_LAYOUT, xaxis_title="Violations (large scale, before repair)", yaxis_title="",
                  height=380, legend_title_text="")
fig.update_xaxes(**AXIS_STYLE)
fig.update_yaxes(**AXIS_STYLE)
plot(fig)

st.divider()

# ── Every rule ────────────────────────────────────────────────────────────
st.subheader("Every check")
choice = st.selectbox("Group", ["All groups"] + list(GROUP_SHORT.values()))
table = report if choice == "All groups" else report[report["group_short"] == choice]
table = table.assign(Status=table["after_repair"].map(lambda n: "✓ pass" if n == 0 else f"✗ {n:,}"))
st.dataframe(
    table[["group_short", "rule", "what", "before_repair", "after_repair", "Status"]].rename(columns={
        "group_short": "Group", "rule": "Check", "what": "What it catches",
        "before_repair": "Before repair", "after_repair": "After repair",
    }),
    hide_index=True, width="stretch",
)

st.info(
    "**What this does and doesn't prove.** Zero violations means the data is consistent with these "
    f"{len(report)} rules, written for this project — not that it is clinically realistic. Group 8 "
    "catches the clear contradictions only; a medication or procedure can still be an odd choice for a "
    "diagnosis without breaking any of its six rules."
)
