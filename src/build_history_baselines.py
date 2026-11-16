"""
build_history_baselines.py
==========================
Recomputes, from the CSVs committed at earlier points in git history, the "before" figures the
Methodology quotes, and writes them to docs/validation_runs/baseline_history.csv so each one
traces to a committed file.

    python src/build_history_baselines.py

Two earlier datasets are read (nothing is regenerated):
  * 94b2de2: the six-year dataset, before the one-year window and the room allocator.
  * c2205fe: the one-year dataset before `sex_at_birth` and the OB/GYN routing rule.
"""

import io
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "validation_runs" / "baseline_history.csv"
SIX_YEAR = "94b2de2"
BEFORE_SEX_AT_BIRTH = "c2205fe"
INPATIENT = ["Standard", "Private", "ICU", "NICU", "Isolation"]
MALE_ONLY = {"O80", "O34.21", "O09.90", "O20.0", "C50.919"}
FEMALE_ONLY = {"C61"}


def show(commit: str, path: str) -> bytes:
    return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=True).stdout


def table(commit: str, name: str, dates=()) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(show(commit, f"app/data/{name}.csv")))
    for c in dates:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def census(adm: pd.DataFrame, rooms: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    stays = adm[adm["admission_status"].isin(["Admitted", "Discharged"]) & adm["room_id"].notna()]
    stays = stays.merge(rooms[["room_id", "room_type"]], on="room_id")
    stays = stays[stays["room_type"].isin(INPATIENT)]
    first = stays["admission_date"].min().normalize()
    days = pd.date_range(first, as_of.normalize(), freq="D")
    start = np.ceil(((stays["admission_date"] - first) / pd.Timedelta(days=1)).to_numpy()).astype(int)
    end = np.ceil(((stays["discharge_date"].fillna(as_of) - first) / pd.Timedelta(days=1)).to_numpy()).astype(int)
    change = np.zeros(len(days) + 1)
    np.add.at(change, np.clip(start, 0, len(days)), 1)
    np.add.at(change, np.clip(end, 0, len(days)), -1)
    return pd.Series(np.cumsum(change)[: len(days)], index=days)


rows = []


def add(figure, value, commit, definition):
    rows.append({"figure": figure, "value": value, "source_commit": commit, "definition": definition})


# ── the six-year dataset ──────────────────────────────────────────────────────────────────────
meta = json.loads(show(SIX_YEAR, "app/data/validation_report_meta.json"))
as_of = pd.Timestamp(meta.get("as_of") or meta["generated_at_utc"])
adm = table(SIX_YEAR, "admissions", ["admission_date", "discharge_date"])
rooms = table(SIX_YEAR, "rooms")
depts = table(SIX_YEAR, "departments")
happened = adm[adm["admission_status"].isin(["Admitted", "Discharged"])]
span_years = (happened["admission_date"].max() - happened["admission_date"].min()).days / 365.25
cen = census(adm, rooms, as_of).iloc[45:]
beds = int(depts["bed_capacity"].sum())
add("six_year_admissions", len(adm), SIX_YEAR, "rows in admissions.csv")
add("six_year_span_years", round(span_years, 1), SIX_YEAR, "years from the first to the last stay that happened")
add("six_year_rooms", len(rooms), SIX_YEAR, "rows in rooms.csv")
add("six_year_department_bed_capacity", beds, SIX_YEAR, "sum of departments.bed_capacity")
add("six_year_average_census", round(float(cen.mean()), 1), SIX_YEAR,
    "patients in an inpatient bed at midnight, averaged after a 45-day warm-up")
add("six_year_average_occupancy_pct", round(100 * float(cen.mean()) / beds, 1), SIX_YEAR,
    "average census over departments.bed_capacity")

s = happened.sort_values(["patient_id", "admission_date", "admission_id"])
end = s["discharge_date"].fillna(as_of)
prev_end = end.groupby(s["patient_id"]).transform(lambda x: x.cummax().shift())    # latest end of any earlier stay
overlaps = int((prev_end > s["admission_date"]).sum())
add("six_year_overlapping_stays", overlaps, SIX_YEAR, "stays that begin while the same patient is in an earlier stay")
add("six_year_overlapping_stays_pct_of_stays", round(100 * overlaps / len(happened), 2), SIX_YEAR,
    "overlapping stays as a share of stays that happened")

# ── the one-year dataset before sex_at_birth ──────────────────────────────────────────────────
adm = table(BEFORE_SEX_AT_BIRTH, "admissions")
pat = table(BEFORE_SEX_AT_BIRTH, "patients")
dx = table(BEFORE_SEX_AT_BIRTH, "diagnoses")
m = adm.merge(pat[["patient_id", "gender", "age"]], on="patient_id")
obgyn_adults = m[(m["department_id"] == "DEP-009") & (m["age"] >= 18) & (m["gender"] != "F")]
add("before_sex_at_birth_adult_obgyn_admissions_not_recorded_F", len(obgyn_adults), BEFORE_SEX_AT_BIRTH,
    "admissions to OB/GYN (DEP-009) of patients aged 18 or more whose gender is not F")
add("before_sex_at_birth_adult_obgyn_stays_not_recorded_F", int(obgyn_adults["admission_status"].isin(["Admitted", "Discharged"]).sum()),
    BEFORE_SEX_AT_BIRTH, "the same, for admissions that happened")
nb = dx.merge(adm[["admission_id", "patient_id"]], on="admission_id").merge(pat[["patient_id", "gender"]], on="patient_id")
nb = nb[nb["gender"] == "NB"]
add("before_sex_at_birth_nb_patients", int((pat["gender"] == "NB").sum()), BEFORE_SEX_AT_BIRTH, "patients with gender NB")
add("before_sex_at_birth_nb_diagnoses", len(nb), BEFORE_SEX_AT_BIRTH, "diagnosis rows of NB patients")
add("before_sex_at_birth_nb_diagnoses_with_sex_specific_code", int(nb["icd10_code"].isin(MALE_ONLY | FEMALE_ONLY).sum()),
    BEFORE_SEX_AT_BIRTH, "of those, rows carrying a male-only or a female-only code (shared_rules.py)")

out = pd.DataFrame(rows)
OUT.parent.mkdir(parents=True, exist_ok=True)
out.to_csv(OUT, index=False)
print(out.to_string(index=False))
print("wrote", OUT)
