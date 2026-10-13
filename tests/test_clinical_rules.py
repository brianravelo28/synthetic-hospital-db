"""Unit tests for the diagnosis-to-treatment mapping (no database needed)."""

import random

import pytest

import clinical_rules as cr
import hospital_generator as gen
import icd10_diagnoses

ALL_CODES = [d["icd10_code"] for d in icd10_diagnoses.DIAGNOSES]
PROC_IDS = [p["procedure_id"] for p in gen.PROCEDURES_DATA]
DRUGS = [m["drug_name"] for m in gen.MEDICATIONS_LIST]
# the test catalog lives inside gen_medical_tests; its names are checked by the run below
TEST_NAMES = sorted({t for tests in cr.FAMILY_TESTS.values() for t in tests})


# ── the mapping only refers to things that exist ─────────────────────────

def test_every_mapped_procedure_and_drug_exists_in_the_generator_catalogs():
    mapped_procs = {p for ps in cr.FAMILY_PROCEDURES.values() for p in ps} | {p for ps in cr.CODE_PROCEDURES.values() for p in ps}
    mapped_drugs = {d for ds in cr.FAMILY_MEDICATIONS.values() for d in ds} | {d for ds in cr.CODE_MEDICATIONS.values() for d in ds}
    assert mapped_procs <= set(PROC_IDS), mapped_procs - set(PROC_IDS)
    assert mapped_drugs <= set(DRUGS), mapped_drugs - set(DRUGS)
    assert set(cr.NOT_FOR_YOUNG_CHILDREN) <= set(DRUGS)
    assert set(cr.DELIVERY_PROCEDURES + cr.ADULT_ONLY_PROCEDURES) <= set(PROC_IDS)


def test_every_mapped_test_exists_in_the_test_catalog(monkeypatch):
    """gen_medical_tests builds its lookup from the catalog inside the function; read it from source."""
    import re
    from pathlib import Path
    src = (Path(gen.__file__)).read_text(encoding="utf-8")
    catalog_names = set(re.findall(r"\('([^']+)', \d+\)", src))
    assert set(TEST_NAMES) <= catalog_names, set(TEST_NAMES) - catalog_names


def test_every_icd_code_has_a_family_with_pools_for_all_three_kinds():
    for code in ALL_CODES:
        fam = cr.family_of(code)
        assert fam in cr.FAMILY_PROCEDURES and fam in cr.FAMILY_MEDICATIONS and fam in cr.FAMILY_TESTS, code


def test_the_four_obstetric_codes_and_newborn_codes_map_where_expected():
    assert {cr.family_of(c) for c in ("O80", "O34.21", "O09.90", "O20.0")} == {"obstetric"}
    assert {cr.family_of(c) for c in ("Z38.00", "P07.30")} == {"newborn"}
    assert cr.family_of("E11.9") == "diabetes" and cr.family_of("E87.1") == "metabolic"
    assert cr.family_of("C50.919") == "oncology"


# ── eligibility: the hard contradictions never come out ──────────────────

def _draw(fn, n=400, **ctx):
    random.seed(11)
    return [fn(**ctx) for _ in range(n)]


@pytest.mark.parametrize("gender,age", [("M", 30), ("F", 8), ("F", 60), ("NB", 25)])
def test_deliveries_only_for_women_of_childbearing_age(gender, age):
    picks = _draw(cr.pick_procedure, dx_codes=["O80", "O34.21"], gender=gender, age=age, all_procedure_ids=PROC_IDS)
    assert not set(picks) & set(cr.DELIVERY_PROCEDURES)


def test_deliveries_do_happen_when_they_are_valid():
    picks = _draw(cr.pick_procedure, dx_codes=["O80"], gender="F", age=28, all_procedure_ids=PROC_IDS)
    assert picks.count("PRC-021") > 250                         # most picks, the rest is general care


@pytest.mark.parametrize("age", [0, 5, 17])
def test_no_major_adult_surgery_on_minors(age):
    codes = ["I21.9", "M16.9", "M17.9", "S72.001A", "K35.80", "C50.919"]
    picks = _draw(cr.pick_procedure, dx_codes=codes, gender="F", age=age, all_procedure_ids=PROC_IDS)
    assert not set(picks) & set(cr.ADULT_ONLY_PROCEDURES)


def test_chemo_and_radiation_need_a_cancer_diagnosis():
    non_cancer = [c for c in ALL_CODES if not c.startswith("C")]
    random.seed(5)
    for _ in range(600):
        codes = random.sample(non_cancer, 3)
        assert cr.pick_procedure(codes, "M", 50, PROC_IDS) not in ("PRC-025", "PRC-026")


def test_insulin_and_metformin_need_a_diabetes_diagnosis():
    non_diabetic = [c for c in ALL_CODES if not c.startswith(("E10", "E11"))]
    random.seed(6)
    for _ in range(600):
        codes = random.sample(non_diabetic, 3)
        drug = cr.pick_medication(codes, "F", 50, DRUGS)
        assert not (drug.startswith("Insulin") or drug == "Metformin"), (codes, drug)


def test_type_1_diabetes_gets_insulin_not_metformin():
    picks = _draw(cr.pick_medication, dx_codes=["E10.9"], gender="F", age=30, all_drug_names=DRUGS)
    assert "Metformin" not in picks and any(p.startswith("Insulin") for p in picks)


def test_pap_smear_only_for_women_21_and_over():
    for gender, age in (("M", 40), ("F", 15), ("NB", 30)):
        picks = _draw(cr.pick_test, dx_codes=["O09.90", "O20.0"], gender=gender, age=age, all_test_names=TEST_NAMES)
        assert "Pap Smear" not in picks
    adult = _draw(cr.pick_test, n=2000, dx_codes=["O09.90"], gender="F", age=30, all_test_names=TEST_NAMES)
    assert "Pap Smear" in adult


def test_young_children_do_not_get_adult_only_drugs():
    codes = ["I50.9", "F32.9", "S72.001A", "C18.9", "E11.9"]
    picks = _draw(cr.pick_medication, n=800, dx_codes=codes, gender="M", age=5, all_drug_names=DRUGS)
    assert not set(picks) & set(cr.NOT_FOR_YOUNG_CHILDREN)


# ── treatments follow the diagnosis ──────────────────────────────────────

def test_appendicitis_leads_to_appendectomy():
    picks = _draw(cr.pick_procedure, dx_codes=["K35.80"], gender="M", age=30, all_procedure_ids=PROC_IDS)
    assert picks.count("PRC-009") / len(picks) > 0.7


def test_general_share_keeps_some_unmatched_care():
    picks = _draw(cr.pick_medication, n=3000, dx_codes=["I10"], gender="M", age=60, all_drug_names=DRUGS)
    off_family = [p for p in picks if p not in cr.FAMILY_MEDICATIONS["cardiac"]]
    assert 0.10 < len(off_family) / len(picks) < 0.30           # around GENERAL_SHARE


def test_no_diagnoses_falls_back_to_general_care():
    pick = cr.pick_procedure([], "M", 40, PROC_IDS)
    assert pick in cr.FAMILY_PROCEDURES["general"]


def test_selection_is_deterministic_under_a_seed():
    def run():
        random.seed(99)
        return [cr.pick_procedure(["I21.9", "J18.9"], "M", 60, PROC_IDS) for _ in range(50)]
    assert run() == run()
