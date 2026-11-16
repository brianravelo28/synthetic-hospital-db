"""
Every figure the README and the Methodology quote is recomputed here from committed files
(the CSVs in app/data/, the recorded runs in docs/validation_runs/, the occupancy summaries),
and the test fails if a document stops containing it. No database needed.

When the data or a recorded run changes, this test lists exactly which sentences to update.
"""

import json
import re
import sqlite3
import tempfile
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"
RUNS = ROOT / "docs" / "validation_runs"
README = (ROOT / "README.md").read_text(encoding="utf-8")
METHOD = (ROOT / "docs" / "METHODOLOGY.md").read_text(encoding="utf-8")


def half_up(x, places=0):
    q = Decimal(1).scaleb(-places)
    return Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP)


def n(x):
    return f"{int(x):,}"


def pct(x, places=1):
    return f"{half_up(x, places)}%"


def when(ts):
    return f"{ts.day} {ts.strftime('%B %Y')}"


def csv(name, **kw):
    return pd.read_csv(DATA / f"{name}.csv", **kw)


def occupancy(size):
    return json.loads((RUNS / f"{size}_occupancy.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def facts():
    adm = csv("admissions", parse_dates=["admission_date", "discharge_date"])
    stays = adm[adm["admission_status"].isin(["Admitted", "Discharged"])]
    sched = adm[adm["admission_status"] == "Scheduled"]
    status = adm["admission_status"].value_counts().to_dict()
    tables = ["departments", "payers", "procedures", "patients", "doctors", "nurses", "employees", "rooms",
              "admissions", "triage", "diagnoses", "patient_procedures", "medications", "medical_tests",
              "staff_shifts", "billing", "billing_line_items"]
    rows = sum(len(csv(t)) for t in tables)
    large, medium, small = occupancy("large"), occupancy("medium"), occupancy("small")
    report = {s: pd.read_csv(RUNS / f"{s}.csv") for s in ("small", "medium", "large")}
    legacy = {s: pd.read_csv(RUNS / f"legacy_generator_{s}.csv") for s in ("small", "medium", "large")}
    hist = pd.read_csv(RUNS / "baseline_history.csv").set_index("figure")["value"]
    base = pd.read_csv(RUNS / "baseline_before_fixes_large.csv")
    pre_occ = pd.read_csv(DATA / "validation_baseline_pre_occupancy.csv").set_index("rule")["count"]
    coh = pd.read_csv(DATA / "validation_baseline_pre_coherence.csv").set_index("rule")["count"]
    return dict(adm=adm, stays=stays, sched=sched, status=status, rows=rows, large=large, medium=medium,
                small=small, report=report, legacy=legacy, hist=hist, base=base, pre_occ=pre_occ, coh=coh,
                rooms=csv("rooms"), patients=csv("patients"), procedures=csv("procedures"))


def sample_question_rows():
    """Rows returned by practice solutions 6, 7 and 11 on the shipped data."""
    import sys
    sys.path.insert(0, str(ROOT / "practice"))
    import load_sqlite
    db = Path(tempfile.mkdtemp()) / "h.db"
    load_sqlite.build(db)
    sql = (ROOT / "practice" / "solutions.sql").read_text(encoding="utf-8")
    parts = re.split(r"(?m)^-- Q(\d+):", sql)
    qs = {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}
    con = sqlite3.connect(db)
    out = {k: len(con.execute(qs[k].split("\n", 1)[1].strip().rstrip(";")).fetchall()) for k in (6, 7, 11)}
    con.close()
    return out


def readme_needles(f):
    L, M, S = f["large"], f["medium"], f["small"]
    a = L["allocation"]
    stays, sched = f["stays"], f["sched"]
    status = f["status"]
    questions = sample_question_rows()
    violations_before = int(f["report"]["large"]["before_repair"].sum())
    return [
        f"{n(len(f['adm']))} admissions, {n(len(f['patients']))} patients",
        f"{L['inpatient_beds']} inpatient beds",
        f"({when(stays['admission_date'].min())} to {when(stays['admission_date'].max())})",
        f"broke {len(f['report']['large'])} consistency rules {violations_before} times",
        f"{pct(L['average_occupancy_pct'], 0)} occupied on average (about {half_up(L['average_census'])} of {L['inpatient_beds']}",
        f"{pct(a['pct_of_needed_bed']['waited'])} of the {n(a['needed_bed'])} admissions that needed a bed waited",
        f"({questions[6]} rows)", f"({questions[7]} rows)", f"({questions[11]} rows;",
        f"{n(f['rows'])} rows",
        f"The 12,000 admissions are {n(status['Discharged'])} discharged, {status['Admitted']} still admitted, "
        f"{status['Scheduled']} scheduled (after the reference date, up to {when(sched['admission_date'].max())}) "
        f"and {status['Cancelled']} cancelled; {a['cancelled_for_no_bed']} of the cancelled",
        f"the {n(len(stays))} admitted or discharged",
        f"the {n(len(stays))} stays plus the {a['cancelled_for_no_bed']} cancelled for lack of one): "
        f"{pct(a['pct_of_needed_bed']['waited'])} waited, {pct(a['pct_of_needed_bed']['lowered_care_level'])} were placed "
        f"at a lower level of care, {pct(a['pct_of_needed_bed']['cancelled_for_no_bed'], 2)} were cancelled",
        f"{n(f['legacy']['large']['before_repair'].sum())} violations on the 51 checks "
        f"that existed then ({n(f['legacy']['small']['before_repair'].sum())} at small size, "
        f"{n(f['legacy']['medium']['before_repair'].sum())} at medium); the current one has {violations_before}",
        f"At large size {n(a['waited'])} admissions ({pct(a['pct_of_needed_bed']['waited'])}) waited for a bed, for a mean of "
        f"{half_up(a['mean_wait_hours'])} hours",
        f"Bed occupancy is {pct(S['average_occupancy_pct'], 0)} at small and {pct(M['average_occupancy_pct'], 0)} at medium",
        "Python 3.11 to 3.13",
    ]


def method_needles(f):
    L, M, S = f["large"], f["medium"], f["small"]
    a = L["allocation"]
    status = f["status"]
    adm = f["adm"]
    needed = a["needed_bed"]
    no_room = int(adm["room_id"].isna().sum())
    legacy = f["legacy"]["large"]
    by_group = legacy.groupby("group")["before_repair"].sum()
    out = [
        f"| Drawn | {n(len(adm))} |", f"| Scheduled (after the reference date) | {status['Scheduled']} |",
        f"| Drawn as cancelled | {status['Cancelled'] - a['cancelled_for_no_bed']} |",
        f"| Needed a bed | {n(needed)} |", f"| Cancelled for lack of a bed | {a['cancelled_for_no_bed']} |",
        f"| Placed (stays) | {n(a['placed'])} |", f"| of which still admitted | {status['Admitted']} |",
        f"| of which discharged | {n(status['Discharged'])} |",
        f"({n(no_room)} rows)",
        f"The 615 `Cancelled` rows in the CSV are the {status['Cancelled'] - a['cancelled_for_no_bed']} drawn plus the {a['cancelled_for_no_bed']}",
    ]
    for label, key in (("Small", S), ("Medium", M), ("Large", L)):
        out.append(f"| {label} | {key['rooms']} | {key['inpatient_beds']} | {key['average_census']} | "
                   f"{key['average_occupancy_pct']}% | {key['busiest_day_pct']}% |")
    for room, plan in (("Standard", 60), ("Private", 58), ("ICU", 78), ("NICU", 75), ("Isolation", 55)):
        out.append(f"| {room} | {plan}% | {L['occupancy_by_type_pct'][room]}% | {L['beds_by_type'][room]}")
    for label, key in (("Small", S), ("Medium", M), ("Large", L)):
        k = key["allocation"]
        r = k["pct_of_needed_bed"]
        canc = "0" if k["cancelled_for_no_bed"] == 0 else f"{k['cancelled_for_no_bed']} ({pct(r['cancelled_for_no_bed'], 2)})"
        out.append(f"| {label} | {n(k['waited'])} ({pct(r['waited'])}; {k['mean_wait_hours']} h) | "
                   f"{k['lowered_care_level']} ({pct(r['lowered_care_level'])}) | "
                   f"{k['moved_after_patients_previous_stay']} ({pct(r['moved_after_patients_previous_stay'])}) | {canc} |")
    out.append(f"({n(S['allocation']['needed_bed'])} at small, {n(M['allocation']['needed_bed'])} at medium, {n(needed)} at large)")
    out.append(f"Intensive {L['condition_mix_pct']['Intensive']}% against 15%")
    # round 1
    names = ["1 · Temporal", "2 · Age-based", "3 · Admission type", "4 · Department", "5 · Diagnoses", "6 · Financial",
             "7 · Realism (detect-only)"]
    cur = f["report"]["large"].groupby("group")["before_repair"].sum()
    for name, g, c in zip(names, by_group.sort_index().tolist(), cur.sort_index().tolist()):
        out.append(f"| {name} | {n(g)} | {n(c)} |")
    out.append(f"| **Total** | **{n(by_group.sum())}** | **{n(cur.sum())}** |")
    out.append(f"Small: {n(f['legacy']['small']['before_repair'].sum())} to {int(f['report']['small']['before_repair'].sum())}. "
               f"Medium: {n(f['legacy']['medium']['before_repair'].sum())} to {int(f['report']['medium']['before_repair'].sum())}.")
    # round 2
    base = f["base"]
    g16 = int(base[base["group"] == "group7_realism"]["count"].sum())
    g16_sorted = base[base["group"] == "group7_realism"].sort_values("count", ascending=False)
    out.append(f"had {int(base[base['group'] != 'group7_realism']['count'].sum())} violations in groups 1 to 6, all one rule")
    out.append(f"{n(g16)} in the 16 realism checks written afterwards")
    out.append(f"{n(base['count'].sum())} together)")
    for _, r in g16_sorted.iterrows():
        out.append(f"| `{r['rule']}` | {n(r['count'])} |")
    # round 3
    out.append(f"{n(f['coh'].sum())} violations in the large dataset of the time")
    for rule in ("diabetes_drug_without_diabetes_dx", "delivery_without_obstetric_dx", "delivery_wrong_patient",
                 "cancer_treatment_without_cancer_dx", "pap_smear_wrong_patient", "adult_surgery_on_minor"):
        out.append(f"{n(f['coh'][rule])};" if rule != "adult_surgery_on_minor" else f"{n(f['coh'][rule])}.")
    # round 4
    h = f["hist"]
    out.append(f"12,000 admissions over {h['six_year_span_years']} years gave an average census of {h['six_year_average_census']} "
               f"against {int(h['six_year_department_bed_capacity'])} department beds and {int(h['six_year_rooms'])} rooms "
               f"({h['six_year_average_occupancy_pct']}% occupancy)")
    out.append(f"{n(f['pre_occ']['room_double_booked'])} double-booked stays at large size, and "
               f"{int(f['pre_occ']['patient_overlapping_admissions'])} stays began")
    out.append(f"{int(h['six_year_overlapping_stays'])} did ({half_up(h['six_year_overlapping_stays_pct_of_stays'], 2)}% of stays")
    # round 5
    out.append(f"{int(h['before_sex_at_birth_nb_diagnoses_with_sex_specific_code'])} of the {int(h['before_sex_at_birth_nb_diagnoses'])} diagnoses of the "
               f"{int(h['before_sex_at_birth_nb_patients'])} NB patients")
    out.append(f"{int(h['before_sex_at_birth_adult_obgyn_admissions_not_recorded_F'])} adult admissions to OB/GYN "
               f"({int(h['before_sex_at_birth_adult_obgyn_stays_not_recorded_F'])} stays)")
    return out


def test_readme_quotes_what_the_data_says(facts):
    missing = [s for s in readme_needles(facts) if s not in README]
    assert not missing, "README no longer contains:\n" + "\n".join(missing)


def test_methodology_quotes_what_the_data_says(facts):
    missing = [s for s in method_needles(facts) if s not in METHOD]
    assert not missing, "METHODOLOGY no longer contains:\n" + "\n".join(missing)


def test_the_share_of_checks_that_can_fire_is_the_one_documented():
    pytest.importorskip("sqlalchemy")
    import test_rules_fire
    outcomes = [v[1] for v in test_rules_fire.MUTATIONS.values()]
    assert outcomes.count("fires") == 56 and outcomes.count("blocked") == 3
    assert "56 of the 59 rules" in README and "For 56 rules the count goes up. For 3" in METHOD
