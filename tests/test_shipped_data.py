"""
Checks on the CSVs actually shipped in app/data/ (what the live dashboard shows).
Pandas re-implementations of the realism rules — no database needed — so a
regenerated dataset that regresses is caught in CI even without MySQL.
"""

import json
import os
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(os.environ.get("HOSPITAL_DATA_DIR") or Path(__file__).resolve().parent.parent / "app" / "data")


def load(name, dates=()):
    df = pd.read_csv(DATA / f"{name}.csv")
    for c in dates:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


@pytest.fixture(scope="module")
def d():
    meta = json.loads((DATA / "validation_report_meta.json").read_text(encoding="utf-8"))
    return {
        "meta": meta,
        "generated_at": pd.Timestamp(meta.get("as_of") or meta["generated_at_utc"]),
        "patients": load("patients", ["birth_date", "registered_date"]),
        "admissions": load("admissions", ["admission_date", "discharge_date"]),
        "billing": load("billing", ["bill_date"]),
        "items": load("billing_line_items"),
        "pp": load("patient_procedures"),
        "procedures": load("procedures"),
        "meds": load("medications"),
        "rooms": load("rooms"),
        "departments": load("departments"),
        "tests": load("medical_tests"),
        "dx": load("diagnoses", ["diagnosis_date"]),
        "doctors": load("doctors", ["hire_date", "birth_date"]),
        "nurses": load("nurses", ["hire_date", "birth_date"]),
        "triage": load("triage"),
        "report": pd.read_csv(DATA / "validation_report.csv"),
    }


def test_row_counts_match_the_recorded_run(d):
    assert len(d["admissions"]) == d["meta"]["admissions"]


def test_foreign_keys_resolve(d):
    adm_ids = set(d["admissions"]["admission_id"])
    assert set(d["billing"]["admission_id"]) <= adm_ids
    assert set(d["dx"]["admission_id"]) <= adm_ids
    assert set(d["admissions"]["patient_id"]) <= set(d["patients"]["patient_id"])
    assert set(d["items"]["bill_id"]) <= set(d["billing"]["bill_id"])
    assert set(d["admissions"]["admitting_doctor_id"]) <= set(d["doctors"]["doctor_id"])


def test_recorded_validation_run_is_clean_apart_from_room_scarcity(d):
    r = d["report"]
    assert len(r) == 59
    leftover = r[r["after_repair"] > 0]
    assert set(leftover["rule"]) <= {"condition_room_mismatch"}


def test_census_is_small_and_recent(d):
    adm = d["admissions"]
    current = adm[adm["admission_status"] == "Admitted"]
    assert (current["admission_date"] >= d["generated_at"] - pd.Timedelta(days=60)).all()
    beds = d["departments"].set_index("department_id")["bed_capacity"]
    per_dept = current.groupby("department_id").size()
    assert (per_dept <= beds.reindex(per_dept.index)).all()          # nobody over their department's beds


def test_scheduled_admissions_are_in_the_future(d):
    adm = d["admissions"]
    sched = adm[adm["admission_status"] == "Scheduled"]
    assert (sched["admission_date"] >= d["generated_at"] - pd.Timedelta(days=1)).all()


def test_no_admission_before_birth(d):
    m = d["admissions"].merge(d["patients"][["patient_id", "birth_date"]], on="patient_id")
    assert (m["admission_date"].dt.normalize() >= m["birth_date"]).all()


def test_bills_exist_only_for_discharged_admissions_and_follow_discharge(d):
    m = d["billing"].merge(d["admissions"], on="admission_id")
    assert (m["admission_status"] == "Discharged").all()
    assert (m["bill_date"] >= m["discharge_date"].dt.normalize()).all()


def test_bill_total_is_the_sum_of_its_line_items(d):
    sums = d["items"].groupby("bill_id")["total_cost"].sum().round(2)
    totals = d["billing"].set_index("bill_id")["total_amount"]
    assert ((totals - sums).abs() < 0.011).all()


def test_line_items_belong_to_the_bills_own_admission(d):
    bill_adm = d["billing"].set_index("bill_id")["admission_id"]
    proc = d["items"][d["items"]["patient_procedure_id"].notna()]
    owner = proc["patient_procedure_id"].map(d["pp"].set_index("patient_procedure_id")["admission_id"])
    assert (owner == proc["bill_id"].map(bill_adm)).all()
    lab = d["items"][d["items"]["test_id"].notna()]
    owner = lab["test_id"].map(d["tests"].set_index("test_id")["admission_id"])
    assert (owner == lab["bill_id"].map(bill_adm)).all()
    assert d["items"].loc[d["items"]["item_type"] == "Procedure", "patient_procedure_id"].notna().all()
    assert d["items"].loc[d["items"]["item_type"] == "Lab", "test_id"].notna().all()


def test_only_real_admissions_have_clinical_records(d):
    ok = set(d["admissions"].loc[d["admissions"]["admission_status"].isin(["Admitted", "Discharged"]),
                                 "admission_id"])
    for key in ("dx", "pp", "tests", "triage"):
        assert set(d[key]["admission_id"]) <= ok, key


def test_infants_have_infant_sized_vitals(d):
    t = d["triage"].merge(d["admissions"][["admission_id", "patient_id"]], on="admission_id") \
                   .merge(d["patients"][["patient_id", "age"]], on="patient_id")
    infants = t[t["age"] <= 1]
    assert len(infants) > 0
    assert (infants["height_cm"] <= 100).all() and (infants["weight_kg"] <= 20).all()


def test_doctors_are_hired_before_acting_and_not_too_young(d):
    m = d["dx"].merge(d["doctors"][["doctor_id", "hire_date"]], on="doctor_id")
    assert (m["diagnosis_date"] >= m["hire_date"]).all()
    m = d["admissions"].merge(d["doctors"][["doctor_id", "hire_date"]],
                              left_on="admitting_doctor_id", right_on="doctor_id")
    assert (m["admission_date"].dt.normalize() >= m["hire_date"]).all()
    for key in ("doctors", "nurses"):
        age_at_hire = (d[key]["hire_date"] - d[key]["birth_date"]).dt.days / 365.25
        assert (age_at_hire >= 21).all(), key


# ── clinical coherence (pandas versions of validator Group 8) ────────────

def _age_at_admission(adm, patients):
    m = adm.merge(patients[["patient_id", "gender", "birth_date"]], on="patient_id")
    m["age_at_adm"] = ((m["admission_date"].dt.normalize() - m["birth_date"]).dt.days // 365.25).astype(int)
    return m[["admission_id", "gender", "age_at_adm"]]


def _procs(d):
    pp = d["pp"].merge(d["procedures"][["procedure_id", "procedure_code"]], on="procedure_id")
    pp["procedure_code"] = pp["procedure_code"].astype(str)
    return pp.merge(_age_at_admission(d["admissions"], d["patients"]), on="admission_id")


def test_deliveries_only_for_women_of_childbearing_age_with_an_obstetric_diagnosis(d):
    deliveries = _procs(d)[lambda x: x["procedure_code"].isin(["59400", "59510"])]
    assert len(deliveries) > 0
    assert (deliveries["gender"] == "F").all()
    assert deliveries["age_at_adm"].between(12, 55).all()
    obstetric = set(d["dx"].loc[d["dx"]["icd10_code"].str.startswith("O"), "admission_id"])
    assert deliveries["admission_id"].isin(obstetric).all()


def test_no_major_adult_surgery_on_minors(d):
    surgery = _procs(d)[lambda x: x["procedure_code"].isin(["33533", "27130", "27447", "27236"])]
    assert len(surgery) > 0
    assert (surgery["age_at_adm"] >= 18).all()


def test_cancer_treatment_only_with_a_cancer_diagnosis(d):
    cancer_tx = _procs(d)[lambda x: x["procedure_code"].isin(["96413", "77373"])]
    assert len(cancer_tx) > 0
    cancer = set(d["dx"].loc[d["dx"]["icd10_code"].str.startswith("C"), "admission_id"])
    assert cancer_tx["admission_id"].isin(cancer).all()


def test_diabetes_drugs_only_with_a_diabetes_diagnosis(d):
    meds = d["meds"]
    diabetes_drugs = meds[meds["drug_name"].str.startswith("Insulin") | (meds["drug_name"] == "Metformin")]
    assert len(diabetes_drugs) > 0
    diabetic = set(d["dx"].loc[d["dx"]["icd10_code"].str.match(r"^E1[0-4]"), "admission_id"])
    assert diabetes_drugs["admission_id"].isin(diabetic).all()


def test_pap_smears_only_for_women_21_and_over(d):
    paps = d["tests"][d["tests"]["test_name"] == "Pap Smear"].merge(
        _age_at_admission(d["admissions"], d["patients"]), on="admission_id")
    assert len(paps) > 0
    assert (paps["gender"] == "F").all() and (paps["age_at_adm"] >= 21).all()


# ── occupancy ─────────────────────────────────────────────────────────────

INPATIENT = ["Standard", "Private", "ICU", "NICU", "Isolation"]


def _stays(d):
    adm = d["admissions"]
    h = adm[adm["admission_status"].isin(["Admitted", "Discharged"])].merge(
        d["rooms"][["room_id", "room_type", "bed_capacity"]], on="room_id")
    h["end"] = h["discharge_date"].fillna(d["generated_at"])
    return h


def test_admissions_cover_about_one_year(d):
    adm = d["admissions"]
    past = adm[adm["admission_status"].isin(["Admitted", "Discharged", "Cancelled"])]
    assert (d["generated_at"] - past["admission_date"].min()).days <= 367


def test_no_room_holds_more_patients_than_it_has_beds(d):
    h = _stays(d)
    for room_id, g in h.groupby("room_id"):
        beds = g["bed_capacity"].iloc[0]
        for start in g["admission_date"]:
            assert ((g["admission_date"] <= start) & (g["end"] > start)).sum() <= beds, room_id


def test_department_beds_equal_the_beds_in_its_inpatient_rooms(d):
    rooms = d["rooms"][d["rooms"]["room_type"].isin(INPATIENT)]
    beds = rooms.groupby("department_id")["bed_capacity"].sum()
    dep = d["departments"].set_index("department_id")["bed_capacity"]
    assert (dep == beds.reindex(dep.index)).all()


def test_procedure_rooms_never_hold_an_admission(d):
    assert not _stays(d)["room_type"].isin(["OR", "ER", "Recovery"]).any()


def test_occupancy_is_realistic_not_empty(d):
    """Average bed occupancy after the first 45 days is far above the old ~6%, and never above 100%."""
    h = _stays(d)
    beds = d["rooms"][d["rooms"]["room_type"].isin(INPATIENT)]["bed_capacity"].sum()
    first = h["admission_date"].min().normalize()
    days = pd.date_range(first + pd.Timedelta(days=45), d["generated_at"].normalize(), freq="D")
    census = [int(((h["admission_date"] <= x) & (h["end"] > x)).sum()) for x in days[::3]]
    assert 0.45 <= (sum(census) / len(census)) / beds <= 0.85
    assert max(census) <= beds


def test_no_patient_is_admitted_while_still_in_an_earlier_stay(d):
    adm = _stays(d).sort_values(["patient_id", "admission_date", "admission_id"])
    prev_end = adm.groupby("patient_id")["end"].shift()
    assert not (prev_end > adm["admission_date"]).any()
