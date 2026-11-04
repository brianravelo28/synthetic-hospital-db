"""
Can each of the 59 checks actually fail?

A check that always returns 0 looks the same as a check that works. For every rule this
test makes one violation inside a transaction (one UPDATE on a freshly generated small
database), runs the check, and rolls the change back. Two outcomes are legitimate:

  fires    the check counts the violation (its count goes up);
  blocked  the table's own CHECK constraint rejects the row, so the violation cannot
           exist in the database at all (the validator rule is then a second line of defence).

The expected outcome is written next to each mutation, so the test also fails if a schema
change turns a "blocked" rule into one that can fire, or the reverse.

Needs a live MariaDB/MySQL and regenerates it (HOSPITAL_DB_URL), like the other
integration tests.
"""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("HOSPITAL_DB_URL"), reason="HOSPITAL_DB_URL not set"),
]

import validate_repair as vr                       # noqa: E402
from shared_rules import AS_OF_SQL                 # noqa: E402


def pick(select: str) -> str:
    """A scalar subquery that MariaDB accepts inside an UPDATE of the table it reads."""
    return f"(SELECT x FROM ({select}) _s)"


def adm(where: str) -> str:
    return pick(f"SELECT admission_id AS x FROM admissions WHERE {where} ORDER BY admission_id LIMIT 1")


def first(table: str, pk: str, where: str = "1=1") -> str:
    return pick(f"SELECT {pk} AS x FROM {table} WHERE {where} ORDER BY {pk} LIMIT 1")


def proc(code: str) -> str:
    return f"(SELECT procedure_id FROM procedures WHERE procedure_code = '{code}')"


def other_dept(column: str = "department_id") -> str:
    return f"IF({column} = 'DEP-001', 'DEP-002', 'DEP-001')"


def patient_of(table: str, pk: str, sex_or_age: str) -> str:
    """The first row of a clinical table whose patient satisfies a condition on patients (alias p)."""
    return pick(
        f"SELECT t.{pk} AS x FROM {table} t JOIN admissions a ON a.admission_id = t.admission_id "
        f"JOIN patients p ON p.patient_id = a.patient_id WHERE {sex_or_age} ORDER BY t.{pk} LIMIT 1")


DISCHARGED = "admission_status = 'Discharged'"
ADMITTED = "admission_status = 'Admitted'"
SCHEDULED = "admission_status = 'Scheduled'"

CROSS_DEPT_SPECIALTIES = "('Anesthesiologist','Hospitalist','Intensivist','Radiologist','Pathologist')"

# rule -> (validator for its group, expected outcome, statements)
T, A, AT, D, DX, F, R, C = (vr.validate_temporal, vr.validate_age, vr.validate_admission_type,
                           vr.validate_department, vr.validate_diagnoses, vr.validate_financial,
                           vr.validate_realism, vr.validate_clinical_coherence)

FIRST_BILL = first("billing", "bill_id")
FIRST_LINE = first("billing_line_items", "line_item_id")

MUTATIONS = {
    # ── Group 1: temporal ────────────────────────────────────────────────
    "discharge_before_admission": (T, "blocked", [
        f"UPDATE admissions SET discharge_date = admission_date - INTERVAL 1 DAY "
        f"WHERE admission_id = {adm(DISCHARGED)}"]),
    "los_inconsistent": (T, "fires", [
        f"UPDATE admissions SET length_of_stay = length_of_stay + 7 WHERE admission_id = {adm(DISCHARGED)}"]),
    "triage_out_of_window": (T, "fires", [
        f"UPDATE triage SET triage_datetime = triage_datetime - INTERVAL 1000 DAY WHERE triage_id = {first('triage', 'triage_id')}"]),
    "diagnosis_out_of_window": (T, "fires", [
        f"UPDATE diagnoses SET diagnosis_date = diagnosis_date - INTERVAL 1000 DAY WHERE diagnosis_id = {first('diagnoses', 'diagnosis_id')}"]),
    "procedure_out_of_window": (T, "fires", [
        f"UPDATE patient_procedures SET procedure_date = procedure_date - INTERVAL 1000 DAY "
        f"WHERE patient_procedure_id = {first('patient_procedures', 'patient_procedure_id')}"]),
    "medication_date_issues": (T, "fires", [
        f"UPDATE medications SET start_date = start_date - INTERVAL 1000 DAY WHERE medication_id = {first('medications', 'medication_id')}"]),
    "test_out_of_window": (T, "fires", [
        f"UPDATE medical_tests SET test_date = test_date - INTERVAL 1000 DAY WHERE test_id = {first('medical_tests', 'test_id')}"]),
    "result_before_test": (T, "blocked", [
        f"UPDATE medical_tests SET result_date = DATE_SUB(DATE(test_date), INTERVAL 1 DAY) "
        f"WHERE test_id = {first('medical_tests', 'test_id', 'result_date IS NOT NULL')}"]),
    "bill_before_discharge": (T, "fires", [
        f"UPDATE billing SET bill_date = bill_date - INTERVAL 1000 DAY WHERE bill_id = {FIRST_BILL}"]),
    "payment_before_bill": (T, "blocked", [
        f"UPDATE billing SET payment_date = DATE_SUB(bill_date, INTERVAL 1 DAY) "
        f"WHERE bill_id = {first('billing', 'bill_id', 'payment_date IS NOT NULL')}"]),

    # ── Group 2: age ────────────────────────────────────────────────────
    # These three turn an existing admission into a "Newborn" one first, so the test does not depend on
    # the random small dataset happening to contain a newborn.
    "newborn_wrong_age": (A, "fires", [
        "UPDATE admissions SET admission_type = 'Newborn' WHERE admission_id = "
        + pick("SELECT a.admission_id AS x FROM admissions a JOIN patients p ON p.patient_id = a.patient_id "
               "WHERE p.age > 0 ORDER BY a.admission_id LIMIT 1")]),
    "newborn_wrong_dept": (A, "fires", [
        "UPDATE admissions SET admission_type = 'Newborn' WHERE admission_id = "
        + adm("department_id NOT IN ('DEP-008', 'DEP-009')")]),
    "newborn_wrong_registered_date": (A, "fires", [
        "UPDATE admissions SET admission_type = 'Newborn' WHERE admission_id = "
        + pick("SELECT a.admission_id AS x FROM admissions a JOIN patients p ON p.patient_id = a.patient_id "
               "WHERE p.registered_date <> DATE(a.admission_date) ORDER BY a.admission_id LIMIT 1")]),
    "pediatric_in_geriatric_dept": (A, "fires", [
        "UPDATE admissions SET department_id = 'DEP-015' WHERE admission_id = "
        + pick("SELECT a.admission_id AS x FROM admissions a JOIN patients p ON p.patient_id = a.patient_id "
               "WHERE p.age BETWEEN 1 AND 17 ORDER BY a.admission_id LIMIT 1")]),
    "adult_in_pediatric_dept": (A, "fires", [
        "UPDATE admissions SET department_id = 'DEP-008' WHERE admission_id = "
        + pick("SELECT a.admission_id AS x FROM admissions a JOIN patients p ON p.patient_id = a.patient_id "
               "WHERE p.age >= 18 ORDER BY a.admission_id LIMIT 1")]),
    "geriatric_newborn_diagnosis": (A, "fires", [
        "UPDATE diagnoses SET icd10_code = 'Z38.00' WHERE diagnosis_id = "
        + patient_of("diagnoses", "diagnosis_id", "p.age > 1")]),

    # ── Group 3: admission type ──────────────────────────────────────────
    "emergency_low_acuity": (AT, "fires", [
        "UPDATE triage SET acuity_level = 5 WHERE triage_id = "
        + pick("SELECT t.triage_id AS x FROM triage t JOIN admissions a ON a.admission_id = t.admission_id "
               "WHERE a.admission_type = 'Emergency' ORDER BY t.triage_id LIMIT 1")]),
    "scheduled_has_triage": (AT, "fires", [
        "UPDATE admissions SET admission_status = 'Scheduled' WHERE admission_id = " + first("triage", "admission_id")]),
    "scheduled_has_diagnoses": (AT, "fires", [
        "UPDATE admissions SET admission_status = 'Scheduled' WHERE admission_id = " + first("diagnoses", "admission_id")]),
    "scheduled_has_procedures": (AT, "fires", [
        "UPDATE admissions SET admission_status = 'Scheduled' WHERE admission_id = " + first("patient_procedures", "admission_id")]),
    "scheduled_has_medications": (AT, "fires", [
        "UPDATE admissions SET admission_status = 'Scheduled' WHERE admission_id = " + first("medications", "admission_id")]),
    "scheduled_has_tests": (AT, "fires", [
        "UPDATE admissions SET admission_status = 'Scheduled' WHERE admission_id = " + first("medical_tests", "admission_id")]),
    "scheduled_has_billing": (AT, "fires", [
        "UPDATE admissions SET admission_status = 'Scheduled' WHERE admission_id = " + first("billing", "admission_id")]),
    "scheduled_has_room": (AT, "fires", [
        "UPDATE admissions SET room_id = (SELECT room_id FROM rooms ORDER BY room_id LIMIT 1) WHERE admission_id = "
        + adm("admission_status = 'Scheduled'")]),

    # ── Group 4: department ──────────────────────────────────────────────
    "doctor_dept_mismatch": (D, "fires", [
        f"UPDATE doctors SET department_id = {other_dept()} WHERE doctor_id = "
        + pick(f"SELECT a.admitting_doctor_id AS x FROM admissions a JOIN doctors d ON d.doctor_id = a.admitting_doctor_id "
               f"WHERE d.specialty NOT IN {CROSS_DEPT_SPECIALTIES} ORDER BY a.admission_id LIMIT 1")]),
    "room_dept_mismatch": (D, "fires", [
        f"UPDATE rooms SET department_id = {other_dept()} WHERE room_id = "
        + first("admissions", "room_id", "room_id IS NOT NULL")]),
    "condition_room_mismatch": (D, "fires", [
        "UPDATE admissions SET patient_condition = 'Intensive' WHERE admission_id = "
        + pick("SELECT a.admission_id AS x FROM admissions a JOIN rooms r ON r.room_id = a.room_id "
               "WHERE r.room_type = 'Standard' ORDER BY a.admission_id LIMIT 1")]),

    # ── Group 5: diagnoses ───────────────────────────────────────────────
    "male_impossible_codes": (DX, "fires", [
        "UPDATE diagnoses SET icd10_code = 'O80' WHERE diagnosis_id = "
        + patient_of("diagnoses", "diagnosis_id", "p.sex_at_birth = 'M'")]),
    "female_impossible_codes": (DX, "fires", [
        "UPDATE diagnoses SET icd10_code = 'C61' WHERE diagnosis_id = "
        + patient_of("diagnoses", "diagnosis_id", "p.sex_at_birth = 'F'")]),
    "newborn_codes_on_adults": (DX, "fires", [
        "UPDATE diagnoses SET icd10_code = 'Z38.00' WHERE diagnosis_id = "
        + patient_of("diagnoses", "diagnosis_id", "p.age > 1")]),

    # ── Group 6: financial ───────────────────────────────────────────────
    "billing_amount_mismatch": (F, "fires", [
        "UPDATE billing SET total_amount = total_amount + 10 WHERE bill_id = "
        + pick("SELECT b.bill_id AS x FROM billing b JOIN billing_line_items li ON li.bill_id = b.bill_id "
               "ORDER BY b.bill_id LIMIT 1")]),
    "denied_with_coverage": (F, "fires", [
        f"UPDATE billing SET payment_status = 'Denied', payment_date = NULL, insurance_covered = 100 WHERE bill_id = {FIRST_BILL}"]),
    "writeoff_with_patient_resp": (F, "fires", [
        f"UPDATE billing SET payment_status = 'Write-Off', payment_date = NULL, patient_responsibility = 100 WHERE bill_id = {FIRST_BILL}"]),
    "paid_missing_payment_date": (F, "fires", [
        f"UPDATE billing SET payment_status = 'Paid', payment_date = NULL WHERE bill_id = {FIRST_BILL}"]),
    "unpaid_has_payment_date": (F, "fires", [
        f"UPDATE billing SET payment_status = 'Pending', payment_date = bill_date WHERE bill_id = {FIRST_BILL}"]),

    # ── Group 7: operational realism ─────────────────────────────────────
    "census_exceeds_bed_capacity": (R, "fires", [
        "UPDATE admissions SET department_id = 'DEP-001' WHERE admission_status = 'Admitted'",
        "UPDATE departments SET bed_capacity = 1 WHERE department_id = 'DEP-001'"]),
    "stale_admitted_over_60d": (R, "fires", [
        f"UPDATE admissions SET admission_date = DATE_SUB({AS_OF_SQL}, INTERVAL 100 DAY) WHERE admission_id = {adm(ADMITTED)}"]),
    "scheduled_in_past": (R, "fires", [
        f"UPDATE admissions SET admission_date = DATE_SUB({AS_OF_SQL}, INTERVAL 5 DAY) WHERE admission_id = {adm(SCHEDULED)}"]),
    "admission_before_birth": (R, "fires", [
        f"UPDATE admissions SET admission_date = '1900-01-01 00:00:00' WHERE admission_id = {adm(DISCHARGED)}"]),
    "room_double_booked": (R, "fires", [
        "SET @a = (SELECT admission_id FROM admissions WHERE admission_status = 'Discharged' "
        "AND room_id IN (SELECT room_id FROM rooms WHERE bed_capacity = 1) ORDER BY admission_id LIMIT 1)",
        "SET @b = (SELECT admission_id FROM admissions WHERE admission_status = 'Discharged' AND admission_id <> @a "
        "ORDER BY admission_id LIMIT 1)",
        "UPDATE admissions b JOIN admissions a ON a.admission_id = @a "
        "SET b.room_id = a.room_id, b.admission_date = a.admission_date, b.discharge_date = a.discharge_date "
        "WHERE b.admission_id = @b"]),
    "patient_overlapping_admissions": (R, "fires", [
        "SET @a = (SELECT admission_id FROM admissions WHERE admission_status = 'Discharged' ORDER BY admission_id LIMIT 1)",
        "SET @b = (SELECT admission_id FROM admissions WHERE admission_status = 'Discharged' AND admission_id <> @a "
        "ORDER BY admission_id LIMIT 1)",
        "UPDATE admissions b JOIN admissions a ON a.admission_id = @a "
        "SET b.patient_id = a.patient_id, b.admission_date = a.admission_date + INTERVAL 1 HOUR, "
        "b.discharge_date = a.discharge_date + INTERVAL 2 HOUR WHERE b.admission_id = @b"]),
    "registered_before_birth": (R, "fires", [
        f"UPDATE patients SET registered_date = DATE_SUB(birth_date, INTERVAL 1 DAY) WHERE patient_id = {first('patients', 'patient_id')}"]),
    "registered_in_future": (R, "fires", [
        f"UPDATE patients SET registered_date = DATE_ADD(DATE({AS_OF_SQL}), INTERVAL 30 DAY) WHERE patient_id = {first('patients', 'patient_id')}"]),
    "bill_before_admission": (R, "fires", [
        f"UPDATE billing SET bill_date = '1900-01-01' WHERE bill_id = {FIRST_BILL}"]),
    "bill_on_undischarged_admission": (R, "fires", [
        "UPDATE admissions SET admission_status = 'Admitted', discharge_date = NULL, length_of_stay = NULL "
        "WHERE admission_id = " + first("billing", "admission_id")]),
    "procedure_item_wrong_admission": (R, "fires", [
        "SET @li = (SELECT line_item_id FROM billing_line_items WHERE item_type = 'Procedure' "
        "AND patient_procedure_id IS NOT NULL ORDER BY line_item_id LIMIT 1)",
        "SET @adm = (SELECT b.admission_id FROM billing_line_items li JOIN billing b ON b.bill_id = li.bill_id "
        "WHERE li.line_item_id = @li)",
        "SET @pp = (SELECT patient_procedure_id FROM patient_procedures WHERE admission_id <> @adm "
        "ORDER BY patient_procedure_id LIMIT 1)",
        "UPDATE billing_line_items SET patient_procedure_id = @pp WHERE line_item_id = @li"]),
    "lab_item_wrong_admission": (R, "fires", [
        "SET @li = (SELECT line_item_id FROM billing_line_items WHERE item_type = 'Lab' "
        "AND test_id IS NOT NULL ORDER BY line_item_id LIMIT 1)",
        "SET @adm = (SELECT b.admission_id FROM billing_line_items li JOIN billing b ON b.bill_id = li.bill_id "
        "WHERE li.line_item_id = @li)",
        "SET @t = (SELECT test_id FROM medical_tests WHERE admission_id <> @adm ORDER BY test_id LIMIT 1)",
        "UPDATE billing_line_items SET test_id = @t WHERE line_item_id = @li"]),
    "procedure_or_lab_item_missing_link": (R, "fires", [
        "UPDATE billing_line_items SET patient_procedure_id = NULL WHERE line_item_id = "
        + first("billing_line_items", "line_item_id", "item_type = 'Procedure'")]),
    "cancelled_has_clinical_records": (R, "fires", [
        "UPDATE admissions SET admission_status = 'Cancelled' WHERE admission_id = " + first("triage", "admission_id")]),
    "pediatric_vitals_implausible": (R, "fires", [
        "SET @t = (SELECT triage_id FROM triage ORDER BY triage_id LIMIT 1)",
        "UPDATE patients p JOIN admissions a ON a.patient_id = p.patient_id JOIN triage t ON t.admission_id = a.admission_id "
        "SET p.age = 5 WHERE t.triage_id = @t",
        "UPDATE triage SET height_cm = 190, weight_kg = 90 WHERE triage_id = @t"]),
    "staff_hired_before_age_21": (R, "fires", [
        f"UPDATE doctors SET hire_date = DATE_ADD(birth_date, INTERVAL 18 YEAR) WHERE doctor_id = {first('doctors', 'doctor_id')}"]),
    "staff_event_before_hire": (R, "fires", [
        "UPDATE doctors SET hire_date = '2100-01-01' WHERE doctor_id = " + first("admissions", "admitting_doctor_id")]),
    "shift_before_hire_or_wrong_dept": (R, "fires", [
        f"UPDATE staff_shifts SET department_id = {other_dept()} WHERE shift_id = "
        + first("staff_shifts", "shift_id", "staff_type = 'Doctor'")]),

    # ── Group 8: clinical coherence ──────────────────────────────────────
    "delivery_wrong_patient": (C, "fires", [
        f"UPDATE patient_procedures SET procedure_id = {proc('59400')} WHERE patient_procedure_id = "
        + patient_of("patient_procedures", "patient_procedure_id", "p.sex_at_birth = 'M'")]),
    "delivery_without_obstetric_dx": (C, "fires", [
        f"UPDATE patient_procedures SET procedure_id = {proc('59400')} WHERE patient_procedure_id = "
        + first("patient_procedures", "patient_procedure_id",
                "NOT EXISTS (SELECT 1 FROM diagnoses d WHERE d.admission_id = patient_procedures.admission_id "
                "AND d.icd10_code LIKE 'O%')")]),
    "adult_surgery_on_minor": (C, "fires", [
        "SET @pp = (SELECT patient_procedure_id FROM patient_procedures ORDER BY patient_procedure_id LIMIT 1)",
        f"UPDATE patient_procedures SET procedure_id = {proc('33533')} WHERE patient_procedure_id = @pp",
        "UPDATE patients p JOIN admissions a ON a.patient_id = p.patient_id "
        "JOIN patient_procedures pp ON pp.admission_id = a.admission_id "
        "SET p.birth_date = DATE_SUB(DATE(a.admission_date), INTERVAL 5 YEAR) WHERE pp.patient_procedure_id = @pp"]),
    "cancer_treatment_without_cancer_dx": (C, "fires", [
        f"UPDATE patient_procedures SET procedure_id = {proc('96413')} WHERE patient_procedure_id = "
        + first("patient_procedures", "patient_procedure_id",
                "NOT EXISTS (SELECT 1 FROM diagnoses d WHERE d.admission_id = patient_procedures.admission_id "
                "AND d.icd10_code LIKE 'C%')")]),
    "diabetes_drug_without_diabetes_dx": (C, "fires", [
        "UPDATE medications SET drug_name = 'Metformin' WHERE medication_id = "
        + first("medications", "medication_id",
                "NOT EXISTS (SELECT 1 FROM diagnoses d WHERE d.admission_id = medications.admission_id "
                "AND d.icd10_code REGEXP '^E1[0-4]')")]),
    "pap_smear_wrong_patient": (C, "fires", [
        "UPDATE medical_tests SET test_name = 'Pap Smear' WHERE test_id = "
        + patient_of("medical_tests", "test_id", "p.sex_at_birth = 'M'")]),
}


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    import run_pipeline
    from sqlalchemy import create_engine
    out = tmp_path_factory.mktemp("faults")
    run_pipeline.run("small", out / "csv", out / "report.csv", do_export=False, summary_path=out / "runs.csv")
    return create_engine(os.environ["HOSPITAL_DB_URL"])


def test_every_rule_has_a_fault_case(engine):
    """The table above covers exactly the 59 rules the validator runs."""
    with engine.connect() as conn:
        reported = {rule for fn in (T, A, AT, D, DX, F, R, C) for rule in fn(conn)}
    assert reported == set(MUTATIONS) and len(MUTATIONS) == 59


@pytest.mark.parametrize("rule", sorted(MUTATIONS))
def test_the_check_fires_or_the_schema_blocks_the_violation(engine, rule):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    group_fn, expected, statements = MUTATIONS[rule]
    with engine.connect() as conn:
        before = group_fn(conn)[rule]
        assert before == 0, f"{rule} should start at 0 on repaired data"
        try:
            for statement in statements:
                conn.execute(text(statement))
        except DBAPIError as exc:
            conn.rollback()
            assert expected == "blocked", f"{rule}: the database rejected the mutation: {exc.orig}"
            assert group_fn(conn)[rule] == 0
            return
        after = group_fn(conn)[rule]
        conn.rollback()
        assert expected == "fires", f"{rule}: the schema no longer blocks this violation; mark it 'fires'"
        assert after > before, f"{rule}: the mutation ran but the check did not notice (before {before}, after {after})"
        assert group_fn(conn)[rule] == 0, "the rollback did not restore the data"
