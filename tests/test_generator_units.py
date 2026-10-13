"""Unit tests for the generator's pure logic — no database needed."""

import random
from datetime import date, datetime, timedelta

import numpy as np
import pytest

import hospital_generator as gen
import icd10_diagnoses
import validate_repair as vr


# ── sampling ──────────────────────────────────────────────────────────────

def test_birth_dates_follow_age_bands():
    random.seed(1)
    ages = [gen.age_from_dob(gen.sample_birth_date()) for _ in range(6000)]
    assert min(ages) >= 0 and max(ages) <= 100
    assert 0.31 <= sum(a >= 65 for a in ages) / len(ages) <= 0.39      # target 0.35
    assert sum(a == 0 for a in ages) / len(ages) < 0.04                  # target 0.015
    assert sum(a <= 17 for a in ages) / len(ages) == pytest.approx(0.15, abs=0.03)


def test_age_band_weights_sum_to_one():
    assert sum(w for _, _, w in gen.AGE_BANDS) == pytest.approx(1.0)
    assert sum(gen.ADMISSION_CATEGORY_P) == pytest.approx(1.0)
    assert sum(gen.NEWBORN_ADM_TYPE_P) == pytest.approx(1.0)
    assert sum(gen.NEWBORN_REPEAT_TYPE_P) == pytest.approx(1.0)
    assert sum(gen.NON_NEWBORN_TYPE_P) == pytest.approx(1.0)


def test_hire_date_respects_minimum_age():
    random.seed(2)
    for _ in range(500):
        birth = date.today() - timedelta(days=random.randint(28 * 366, 70 * 365))
        hired = gen.hire_date_for(birth, date(2000, 1, 1), 25)
        assert hired <= date.today()
        assert (hired - birth).days >= 25 * 365


# ── staff pool: nobody acts before they were hired ───────────────────────

def _pool():
    return gen.StaffPool([
        ("A", date(2010, 1, 1), "D1"),
        ("B", date(2022, 6, 1), "D1"),
        ("C", date(2024, 1, 1), "D2"),
    ])


def test_pool_only_picks_people_already_hired():
    pool = _pool()
    for _ in range(200):
        assert pool.pick(date(2015, 1, 1)) == "A"
        assert pool.pick(date(2023, 1, 1), "D1") in {"A", "B"}


def test_pool_pick_falls_back_to_earliest_hire():
    assert _pool().pick(date(2001, 1, 1)) == "A"


def test_pool_pushes_admission_forward_when_nobody_in_dept_is_hired_yet():
    pool = _pool()
    doc, when = pool.pick_with_date(datetime(2020, 3, 1, 9, 0), "D2")
    assert doc == "C"
    assert when.date() >= date(2024, 1, 1)
    doc, when = pool.pick_with_date(datetime(2023, 3, 1, 9, 0), "D1")
    assert doc in {"A", "B"} and when == datetime(2023, 3, 1, 9, 0)


# ── diagnosis sampling ───────────────────────────────────────────────────

@pytest.mark.parametrize("dept,gender,age,forbidden", [
    ("OB/GYN", "M", 30, gen.MALE_IMPOSSIBLE_CODES),          # pool is almost all female-only
    ("Urology", "F", 40, gen.FEMALE_IMPOSSIBLE_CODES),
    ("Pediatrics", "F", 5, gen.NEWBORN_ONLY_CODES),
    ("Internal Medicine", "M", 80, gen.MALE_IMPOSSIBLE_CODES | gen.NEWBORN_ONLY_CODES),
])
def test_diagnosis_sampling_never_returns_impossible_codes(dept, gender, age, forbidden):
    np.random.seed(3)
    for _ in range(1500):
        assert gen._sample_valid_diagnosis(dept, gender, age)["icd10_code"] not in forbidden


# ── age-banded vitals stay inside what the validator calls plausible ─────

@pytest.mark.parametrize("age", [0, 1, 2, 12, 13, 17, 18, 45, 90])
def test_vitals_ranges_are_plausible_for_age(age):
    v = gen._vitals_for_age(age)
    if age <= 1:
        assert v["h"][1] <= 100 and v["w"][1] <= 20
    elif age <= 12:
        assert v["h"][1] <= 170 and v["w"][1] <= 80
    # inside the table's CHECK constraints (hospital_db.sql)
    assert 60 <= v["sbp"][0] and v["sbp"][1] <= 250
    assert 30 <= v["dbp"][0] and v["dbp"][1] <= 150
    assert 20 <= v["hr"][0] and v["hr"][1] <= 300
    assert 4 <= v["rr"][0] and v["rr"][1] <= 60


# ── generator and validator carry copies of the same constants ───────────

def test_generator_and_validator_share_one_copy_of_each_constant():
    """They used to carry separate copies held together by "must match" comments."""
    import shared_rules
    assert gen.CONDITION_ROOM_MAP is vr.CONDITION_ROOM_MAP is shared_rules.CONDITION_ROOM_MAP
    assert gen.MALE_IMPOSSIBLE_CODES is vr.MALE_IMPOSSIBLE_CODES is shared_rules.MALE_IMPOSSIBLE_CODES
    assert gen.FEMALE_IMPOSSIBLE_CODES is vr.FEMALE_IMPOSSIBLE_CODES is shared_rules.FEMALE_IMPOSSIBLE_CODES
    assert gen.NEWBORN_ONLY_CODES is vr.NEWBORN_ONLY_CODES is shared_rules.NEWBORN_ONLY_CODES
    assert gen.PAYER_COVERAGE is vr.PAYER_COVERAGE is shared_rules.PAYER_COVERAGE
    assert gen.AS_OF is vr.AS_OF is shared_rules.AS_OF
    assert set(gen.NEWBORN_DEPT_POOL) == shared_rules.OB_NEWBORN_DEPTS


def test_reference_date_can_be_pinned_by_env_var():
    import subprocess, sys
    code = "import sys; sys.path.insert(0, 'data'); import shared_rules as s; print(s.AS_OF, s.AS_OF_SQL)"
    root = __import__("pathlib").Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root,
                         env={**__import__("os").environ, "HOSPITAL_AS_OF": "2026-10-13 12:00:00"}).stdout.strip()
    assert out == "2026-10-13 12:00:00 '2026-10-13 12:00:00'"


def test_no_raw_clock_or_sql_randomness_left_in_the_pipeline():
    """Everything reads the one reference date; repair uses hashes, not RAND()."""
    import re
    root = __import__("pathlib").Path(__file__).resolve().parent.parent
    for path in ("data/hospital_generator.py", "src/validate_repair.py"):
        text = (root / path).read_text(encoding="utf-8")
        assert not re.search(r"datetime\.now\(\)|date\.today\(\)|NOW\(\)|CURDATE\(\)|RAND\(\)", text), path


def test_every_room_type_has_a_billing_rate():
    assert set(gen.ROOM_RATES) == set(gen.ROOM_TYPES)


def test_every_condition_has_a_room_rule_for_each_known_type():
    known = set(gen.ROOM_TYPES)
    for allowed in gen.CONDITION_ROOM_MAP.values():
        assert set(allowed) <= known


# ── ICD-10 catalog bookkeeping (a stale count once slipped into the docs) ─

def test_icd10_summary_matches_catalog():
    assert len(icd10_diagnoses.DIAGNOSES) == icd10_diagnoses.TOTAL_DIAGNOSES
    assert sum(icd10_diagnoses.CATEGORY_SUMMARY.values()) == len(icd10_diagnoses.DIAGNOSES)
    codes = [d["icd10_code"] for d in icd10_diagnoses.DIAGNOSES]
    assert len(codes) == len(set(codes))
