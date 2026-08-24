"""
validate_repair.py  (v1)
========================
Generate-validate-repair module for hospital_db.

Validates semantic integrity across 6 rule groups and repairs violations
in the correct dependency order.

Rule groups (executed in sequence):
    1. Temporal          — date windows, LOS, registered_date
    2. Age-based         — newborn, pediatric, geriatric rules
    3. Admission type    — ESI scores, scheduled record cleanup
    4. Department        — doctor/room/condition alignment
    5. Diagnosis         — gender-impossible codes, dept alignment
    6. Financial         — amount reconciliation, payment logic

Usage (Jupyter):
    exec(open('validate_repair.py').read())

    # Inspect violations before touching anything
    with engine.connect() as conn:
        report = validate_all(conn)
    print_report(report)

    # Apply all repairs in sequence
    run_repair(engine)

    # Confirm — should be all zeros
    with engine.connect() as conn:
        report = validate_all(conn)
    print_report(report)
"""

import random
import numpy as np
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine, text
from collections import defaultdict

from icd10_diagnoses import sample_diagnosis, get_diagnoses_for_department

DB_URL = "mysql+pymysql://root:@localhost/hospital_db"


# =============================================================================
# CONSTANTS
# =============================================================================

# Specialties that legitimately cross department boundaries
CROSS_DEPT_SPECIALTIES = {
    'Anesthesiologist', 'Hospitalist', 'Intensivist',
    'Radiologist', 'Pathologist'
}

# Allowed room types per patient condition
CONDITION_ROOM_MAP = {
    'Intensive': ['ICU', 'NICU'],
    'Maximum':   ['ICU', 'NICU', 'Private', 'Isolation'],
    'Moderate':  ['Standard', 'Private'],
    'Minimal':   ['Standard', 'Recovery', 'Private'],
}

# Minimum condition required by room type
# Used as fallback when no appropriate room exists in the department
ROOM_MIN_CONDITION = {
    'ICU':      'Intensive',
    'NICU':     'Maximum',
    'Isolation':'Maximum',
    'Private':  'Minimal',
    'Standard': 'Minimal',
    'Recovery': 'Minimal',
    'ER':       'Minimal',
    'OR':       'Minimal',
}

# ICD-10 codes that are biologically impossible for certain genders/ages
MALE_IMPOSSIBLE_CODES  = {'O80', 'O34.21', 'O09.90', 'O20.0', 'C50.919'}
FEMALE_IMPOSSIBLE_CODES = {'C61'}
NEWBORN_ONLY_CODES      = {'Z38.00', 'P07.30'}

# OB/GYN and newborn departments
OB_NEWBORN_DEPTS = {'DEP-008', 'DEP-009'}

# Payer coverage rates — must match hospital_generator.py
PAYER_COVERAGE = {
    'Medicare':             0.80,
    'Medicaid':             0.72,
    'Private Insurance':    0.85,
    'Self-Pay':             0.00,
    'Workers Compensation': 0.90,
    'CHIP':                 0.75,
}


# =============================================================================
# HELPERS
# =============================================================================

def get_dept_name_map(conn) -> dict:
    """Return {department_id: dep_name} for ICD-10 department filtering."""
    result = conn.execute(text(
        "SELECT department_id, dep_name FROM departments"
    ))
    return {row[0]: row[1] for row in result}


def get_dept_doctor_map(conn) -> dict:
    """Return {department_id: [doctor_ids]} for reassignment."""
    result = conn.execute(text(
        "SELECT doctor_id, department_id FROM doctors"
    ))
    m = defaultdict(list)
    for row in result:
        m[row[1]].append(row[0])
    return dict(m)


def get_dept_room_map(conn, room_types: list = None) -> dict:
    """
    Return {department_id: [room_ids]} optionally filtered by room_type list.
    """
    if room_types:
        placeholders = ', '.join(f"'{rt}'" for rt in room_types)
        sql = f"SELECT room_id, department_id FROM rooms WHERE room_type IN ({placeholders})"
    else:
        sql = "SELECT room_id, department_id FROM rooms"
    result = conn.execute(text(sql))
    m = defaultdict(list)
    for row in result:
        m[row[1]].append(row[0])
    return dict(m)


def batch_update(conn, sql: str, rows: list, batch_size: int = 500):
    """Execute a parameterized UPDATE in batches to handle large datasets."""
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        if chunk:
            conn.execute(text(sql), chunk)


def _count(conn, sql: str) -> int:
    result = conn.execute(text(sql))
    row = result.fetchone()
    return int(row[0]) if row else 0


# =============================================================================
# GROUP 1 — TEMPORAL RULES
# =============================================================================

def validate_temporal(conn) -> dict:
    return {
        'discharge_before_admission': _count(conn, """
            SELECT COUNT(*) FROM admissions
            WHERE discharge_date IS NOT NULL AND discharge_date < admission_date
        """),
        'los_inconsistent': _count(conn, """
            SELECT COUNT(*) FROM admissions
            WHERE admission_status = 'Discharged'
              AND discharge_date IS NOT NULL
              AND length_of_stay != DATEDIFF(discharge_date, admission_date)
        """),
        'triage_out_of_window': _count(conn, """
            SELECT COUNT(*) FROM triage t
            JOIN admissions a ON t.admission_id = a.admission_id
            WHERE t.triage_datetime < a.admission_date
               OR (a.discharge_date IS NOT NULL AND t.triage_datetime > a.discharge_date)
        """),
        'diagnosis_out_of_window': _count(conn, """
            SELECT COUNT(*) FROM diagnoses d
            JOIN admissions a ON d.admission_id = a.admission_id
            WHERE d.diagnosis_date < DATE(a.admission_date)
               OR (a.discharge_date IS NOT NULL AND d.diagnosis_date > DATE(a.discharge_date))
        """),
        'procedure_out_of_window': _count(conn, """
            SELECT COUNT(*) FROM patient_procedures pp
            JOIN admissions a ON pp.admission_id = a.admission_id
            WHERE pp.procedure_date < a.admission_date
               OR (a.discharge_date IS NOT NULL AND pp.procedure_date > a.discharge_date)
        """),
        'medication_date_issues': _count(conn, """
            SELECT COUNT(*) FROM medications m
            JOIN admissions a ON m.admission_id = a.admission_id
            WHERE m.start_date < DATE(a.admission_date)
               OR (m.end_date IS NOT NULL AND m.end_date < m.start_date)
               OR (a.discharge_date IS NOT NULL
                   AND m.med_status IN ('Completed','Discontinued')
                   AND m.end_date > DATE(a.discharge_date))
        """),
        'test_out_of_window': _count(conn, """
            SELECT COUNT(*) FROM medical_tests mt
            JOIN admissions a ON mt.admission_id = a.admission_id
            WHERE mt.test_date < a.admission_date
               OR (a.discharge_date IS NOT NULL AND mt.test_date > a.discharge_date)
        """),
        'result_before_test': _count(conn, """
            SELECT COUNT(*) FROM medical_tests
            WHERE result_date IS NOT NULL AND result_date < DATE(test_date)
        """),
        'bill_before_discharge': _count(conn, """
            SELECT COUNT(*) FROM billing b
            JOIN admissions a ON b.admission_id = a.admission_id
            WHERE a.admission_status = 'Discharged'
              AND a.discharge_date IS NOT NULL
              AND b.bill_date < DATE(a.discharge_date)
        """),
        'payment_before_bill': _count(conn, """
            SELECT COUNT(*) FROM billing
            WHERE payment_status = 'Paid'
              AND payment_date IS NOT NULL
              AND payment_date < bill_date
        """),
    }


def repair_temporal(conn):
    print("  [Group 1] Repairing temporal violations...")

    # ── Discharge before admission — add 1 day ────────────────────────────
    conn.execute(text("""
        UPDATE admissions
        SET discharge_date = DATE_ADD(admission_date, INTERVAL 1 DAY)
        WHERE discharge_date IS NOT NULL AND discharge_date < admission_date
    """))

    # ── Recalculate length_of_stay ─────────────────────────────────────────
    conn.execute(text("""
        UPDATE admissions
        SET length_of_stay = DATEDIFF(discharge_date, admission_date)
        WHERE admission_status = 'Discharged' AND discharge_date IS NOT NULL
    """))

    # ── Triage: clamp to admission window ──────────────────────────────────
    conn.execute(text("""
        UPDATE triage t
        JOIN admissions a ON t.admission_id = a.admission_id
        SET t.triage_datetime = a.admission_date
        WHERE t.triage_datetime < a.admission_date
    """))
    conn.execute(text("""
        UPDATE triage t
        JOIN admissions a ON t.admission_id = a.admission_id
        SET t.triage_datetime = a.discharge_date
        WHERE a.discharge_date IS NOT NULL AND t.triage_datetime > a.discharge_date
    """))

    # ── Diagnoses: clamp to admission window ───────────────────────────────
    conn.execute(text("""
        UPDATE diagnoses d
        JOIN admissions a ON d.admission_id = a.admission_id
        SET d.diagnosis_date = DATE(a.admission_date)
        WHERE d.diagnosis_date < DATE(a.admission_date)
    """))
    conn.execute(text("""
        UPDATE diagnoses d
        JOIN admissions a ON d.admission_id = a.admission_id
        SET d.diagnosis_date = DATE(a.discharge_date)
        WHERE a.discharge_date IS NOT NULL
          AND d.diagnosis_date > DATE(a.discharge_date)
    """))

    # ── Procedures: clamp to admission window ──────────────────────────────
    conn.execute(text("""
        UPDATE patient_procedures pp
        JOIN admissions a ON pp.admission_id = a.admission_id
        SET pp.procedure_date = a.admission_date
        WHERE pp.procedure_date < a.admission_date
    """))
    conn.execute(text("""
        UPDATE patient_procedures pp
        JOIN admissions a ON pp.admission_id = a.admission_id
        SET pp.procedure_date = a.discharge_date
        WHERE a.discharge_date IS NOT NULL
          AND pp.procedure_date > a.discharge_date
    """))

    # ── Medications: clamp start_date, then fix end_date ──────────────────
    conn.execute(text("""
        UPDATE medications m
        JOIN admissions a ON m.admission_id = a.admission_id
        SET m.start_date = DATE(a.admission_date)
        WHERE m.start_date < DATE(a.admission_date)
    """))
    conn.execute(text("""
        UPDATE medications m
        SET m.end_date = m.start_date
        WHERE m.end_date IS NOT NULL AND m.end_date < m.start_date
    """))
    conn.execute(text("""
        UPDATE medications m
        JOIN admissions a ON m.admission_id = a.admission_id
        SET m.end_date = DATE(a.discharge_date)
        WHERE a.discharge_date IS NOT NULL
          AND m.med_status IN ('Completed','Discontinued')
          AND m.end_date > DATE(a.discharge_date)
    """))

    # ── Medical tests: clamp to admission window ───────────────────────────
    conn.execute(text("""
        UPDATE medical_tests mt
        JOIN admissions a ON mt.admission_id = a.admission_id
        SET mt.test_date = a.admission_date
        WHERE mt.test_date < a.admission_date
    """))
    conn.execute(text("""
        UPDATE medical_tests mt
        JOIN admissions a ON mt.admission_id = a.admission_id
        SET mt.test_date = a.discharge_date
        WHERE a.discharge_date IS NOT NULL AND mt.test_date > a.discharge_date
    """))
    conn.execute(text("""
        UPDATE medical_tests
        SET result_date = DATE(test_date)
        WHERE result_date IS NOT NULL AND result_date < DATE(test_date)
    """))

    # ── Bill date: clamp to discharge date ────────────────────────────────
    conn.execute(text("""
        UPDATE billing b
        JOIN admissions a ON b.admission_id = a.admission_id
        SET b.bill_date = DATE(a.discharge_date)
        WHERE a.admission_status = 'Discharged'
          AND a.discharge_date IS NOT NULL
          AND b.bill_date < DATE(a.discharge_date)
    """))

    # ── Due date: always bill_date + 30 ───────────────────────────────────
    conn.execute(text("""
        UPDATE billing
        SET due_date = DATE_ADD(bill_date, INTERVAL 30 DAY)
    """))

    # ── Payment date before bill date ─────────────────────────────────────
    conn.execute(text("""
        UPDATE billing
        SET payment_date = DATE_ADD(bill_date, INTERVAL FLOOR(5 + RAND() * 85) DAY)
        WHERE payment_status = 'Paid'
          AND (payment_date IS NULL OR payment_date < bill_date)
    """))

    # ── Registered date: probabilistic by age (Python loop) ───────────────
    result = conn.execute(text("""
        SELECT p.patient_id, p.age,
               COALESCE(MIN(DATE(a.admission_date)), CURDATE()) AS first_adm
        FROM patients p
        LEFT JOIN admissions a ON p.patient_id = a.patient_id
        GROUP BY p.patient_id, p.age
    """))
    rows = result.fetchall()
    updates = []
    for row in rows:
        patient_id, age, first_adm = row
        if isinstance(first_adm, str):
            first_adm = date.fromisoformat(first_adm)

        if age <= 21:
            if random.random() < 0.55:
                reg_date = first_adm
            else:
                delta    = random.randint(0, 90)
                reg_date = first_adm - timedelta(days=delta)
        else:
            if random.random() < 0.25:
                reg_date = first_adm
            else:
                delta    = random.randint(0, 730)
                reg_date = first_adm - timedelta(days=delta)

        updates.append({"patient_id": patient_id, "registered_date": reg_date})

    batch_update(conn,
        "UPDATE patients SET registered_date = :registered_date "
        "WHERE patient_id = :patient_id",
        updates
    )
    print(f"    Registered dates adjusted for {len(updates)} patients")
    print("    Group 1 complete.")


# =============================================================================
# GROUP 2 — AGE-BASED RULES
# =============================================================================

def validate_age(conn) -> dict:
    return {
        'newborn_wrong_age': _count(conn, """
            SELECT COUNT(*) FROM patients p
            JOIN admissions a ON p.patient_id = a.patient_id
            WHERE a.admission_type = 'Newborn' AND p.age > 0
        """),
        'newborn_wrong_dept': _count(conn, """
            SELECT COUNT(*) FROM admissions
            WHERE admission_type = 'Newborn'
              AND department_id NOT IN ('DEP-008','DEP-009')
        """),
        'newborn_wrong_registered_date': _count(conn, """
            SELECT COUNT(*) FROM patients p
            JOIN admissions a ON p.patient_id = a.patient_id
            WHERE a.admission_type = 'Newborn'
              AND p.registered_date != DATE(a.admission_date)
        """),
        'pediatric_in_geriatric_dept': _count(conn, """
            SELECT COUNT(*) FROM patients p
            JOIN admissions a ON p.patient_id = a.patient_id
            WHERE p.age BETWEEN 1 AND 17
              AND a.department_id = 'DEP-015'
        """),
        'adult_in_pediatric_dept': _count(conn, """
            SELECT COUNT(*) FROM patients p
            JOIN admissions a ON p.patient_id = a.patient_id
            WHERE p.age >= 18 AND a.department_id = 'DEP-008'
        """),
        'geriatric_newborn_diagnosis': _count(conn, """
            SELECT COUNT(*) FROM diagnoses d
            JOIN admissions a ON d.admission_id = a.admission_id
            JOIN patients p ON a.patient_id = p.patient_id
            WHERE p.age > 1 AND d.icd10_code IN ('Z38.00','P07.30')
        """),
    }


def repair_age(conn):
    print("  [Group 2] Repairing age-based violations...")

    # ── Newborn birth_date, age, registered_date (Python for randomness) ──
    result = conn.execute(text("""
        SELECT DISTINCT p.patient_id, DATE(a.admission_date) AS adm_date
        FROM patients p
        JOIN admissions a ON p.patient_id = a.patient_id
        WHERE a.admission_type = 'Newborn'
    """))
    rows = result.fetchall()
    updates = []
    for row in rows:
        pid, adm_date = row
        if isinstance(adm_date, str):
            adm_date = date.fromisoformat(adm_date)
        birth_date = adm_date - timedelta(days=random.randint(0, 3))
        updates.append({
            "patient_id":      pid,
            "birth_date":      birth_date,
            "age":             0,
            "registered_date": adm_date,
        })

    batch_update(conn,
        "UPDATE patients SET birth_date = :birth_date, age = :age, "
        "registered_date = :registered_date WHERE patient_id = :patient_id",
        updates
    )
    print(f"    Fixed birth/age/registered for {len(updates)} newborn patients")

    # ── Newborn admissions: reassign to OB/GYN ────────────────────────────
    conn.execute(text("""
        UPDATE admissions SET department_id = 'DEP-009'
        WHERE admission_type = 'Newborn'
          AND department_id NOT IN ('DEP-008','DEP-009')
    """))

    # ── Pediatric patients in Geriatric → reassign to Pediatrics ──────────
    conn.execute(text("""
        UPDATE admissions a
        JOIN patients p ON a.patient_id = p.patient_id
        SET a.department_id = 'DEP-008'
        WHERE p.age BETWEEN 1 AND 17 AND a.department_id = 'DEP-015'
    """))

    # ── Adults in Pediatrics → reassign to Internal Medicine ──────────────
    conn.execute(text("""
        UPDATE admissions a
        JOIN patients p ON a.patient_id = p.patient_id
        SET a.department_id = 'DEP-005'
        WHERE p.age >= 18 AND a.department_id = 'DEP-008'
    """))

    # ── Geriatric newborn/pediatric diagnoses → resample ──────────────────
    result = conn.execute(text("""
        SELECT d.diagnosis_id, a.department_id
        FROM diagnoses d
        JOIN admissions a ON d.admission_id = a.admission_id
        JOIN patients p ON a.patient_id = p.patient_id
        WHERE p.age > 1 AND d.icd10_code IN ('Z38.00','P07.30')
    """))
    rows        = result.fetchall()
    dept_map    = get_dept_name_map(conn)
    dx_updates  = []
    for row in rows:
        dx_id, dept_id = row
        dept_name = dept_map.get(dept_id, 'Internal Medicine')
        new_dx    = sample_diagnosis(dept_name)
        dx_updates.append({"diagnosis_id": dx_id, "icd10_code": new_dx['icd10_code']})

    batch_update(conn,
        "UPDATE diagnoses SET icd10_code = :icd10_code "
        "WHERE diagnosis_id = :diagnosis_id",
        dx_updates
    )
    print(f"    Resampled {len(dx_updates)} impossible age-diagnosis combinations")
    print("    Group 2 complete.")


# =============================================================================
# GROUP 3 — ADMISSION TYPE RULES
# =============================================================================

def validate_admission_type(conn) -> dict:
    return {
        'emergency_low_acuity': _count(conn, """
            SELECT COUNT(*) FROM triage t
            JOIN admissions a ON t.admission_id = a.admission_id
            WHERE a.admission_type = 'Emergency' AND t.acuity_level > 3
        """),
        'scheduled_has_triage': _count(conn, """
            SELECT COUNT(*) FROM triage t
            JOIN admissions a ON t.admission_id = a.admission_id
            WHERE a.admission_status = 'Scheduled'
        """),
        'scheduled_has_diagnoses': _count(conn, """
            SELECT COUNT(*) FROM diagnoses d
            JOIN admissions a ON d.admission_id = a.admission_id
            WHERE a.admission_status = 'Scheduled'
        """),
        'scheduled_has_procedures': _count(conn, """
            SELECT COUNT(*) FROM patient_procedures pp
            JOIN admissions a ON pp.admission_id = a.admission_id
            WHERE a.admission_status = 'Scheduled'
        """),
        'scheduled_has_medications': _count(conn, """
            SELECT COUNT(*) FROM medications m
            JOIN admissions a ON m.admission_id = a.admission_id
            WHERE a.admission_status = 'Scheduled'
        """),
        'scheduled_has_tests': _count(conn, """
            SELECT COUNT(*) FROM medical_tests mt
            JOIN admissions a ON mt.admission_id = a.admission_id
            WHERE a.admission_status = 'Scheduled'
        """),
        'scheduled_has_billing': _count(conn, """
            SELECT COUNT(*) FROM billing b
            JOIN admissions a ON b.admission_id = a.admission_id
            WHERE a.admission_status IN ('Scheduled','Cancelled')
        """),
        'scheduled_has_room': _count(conn, """
            SELECT COUNT(*) FROM admissions
            WHERE admission_status = 'Scheduled' AND room_id IS NOT NULL
        """),
    }


def repair_admission_type(conn):
    print("  [Group 3] Repairing admission type violations...")

    # ── Emergency: upgrade low acuity to ESI 1-3 ──────────────────────────
    conn.execute(text("""
        UPDATE triage t
        JOIN admissions a ON t.admission_id = a.admission_id
        SET t.acuity_level = FLOOR(1 + RAND() * 3)
        WHERE a.admission_type = 'Emergency' AND t.acuity_level > 3
    """))

    # ── Scheduled: remove room assignment ─────────────────────────────────
    conn.execute(text("""
        UPDATE admissions SET room_id = NULL
        WHERE admission_status = 'Scheduled'
    """))

    # ── Scheduled/Cancelled: delete clinical records ───────────────────────
    # ON DELETE CASCADE handles child records of these tables
    # but we delete directly to be explicit
    for table in ['triage', 'diagnoses', 'patient_procedures',
                  'medications', 'medical_tests']:
        conn.execute(text(f"""
            DELETE t FROM {table} t
            JOIN admissions a ON t.admission_id = a.admission_id
            WHERE a.admission_status = 'Scheduled'
        """))

    # ── Scheduled/Cancelled: delete billing (line items cascade) ──────────
    conn.execute(text("""
        DELETE bli FROM billing_line_items bli
        JOIN billing b ON bli.bill_id = b.bill_id
        JOIN admissions a ON b.admission_id = a.admission_id
        WHERE a.admission_status IN ('Scheduled','Cancelled')
    """))
    conn.execute(text("""
        DELETE b FROM billing b
        JOIN admissions a ON b.admission_id = a.admission_id
        WHERE a.admission_status IN ('Scheduled','Cancelled')
    """))

    print("    Group 3 complete.")


# =============================================================================
# GROUP 4 — DEPARTMENT-STAFF-ROOM CONSISTENCY
# =============================================================================

def validate_department(conn) -> dict:
    return {
        'doctor_dept_mismatch': _count(conn, """
            SELECT COUNT(*) FROM admissions a
            JOIN doctors d ON a.admitting_doctor_id = d.doctor_id
            WHERE a.department_id != d.department_id
              AND d.specialty NOT IN (
                'Anesthesiologist','Hospitalist','Intensivist',
                'Radiologist','Pathologist'
              )
        """),
        'room_dept_mismatch': _count(conn, """
            SELECT COUNT(*) FROM admissions a
            JOIN rooms r ON a.room_id = r.room_id
            WHERE a.department_id != r.department_id
              AND a.room_id IS NOT NULL
        """),
        'condition_room_mismatch': _count(conn, """
            SELECT COUNT(*) FROM admissions a
            JOIN rooms r ON a.room_id = r.room_id
            WHERE a.room_id IS NOT NULL AND (
                (a.patient_condition = 'Intensive' AND r.room_type NOT IN ('ICU','NICU'))
             OR (a.patient_condition = 'Maximum'   AND r.room_type NOT IN ('ICU','NICU','Private','Isolation'))
             OR (a.patient_condition = 'Moderate'  AND r.room_type NOT IN ('Standard','Private'))
             OR (a.patient_condition = 'Minimal'   AND r.room_type NOT IN ('Standard','Recovery','Private'))
            )
        """),
    }


def repair_department(conn):
    print("  [Group 4] Repairing department consistency violations...")

    dept_doctor_map = get_dept_doctor_map(conn)

    # ── Doctor-department mismatch ─────────────────────────────────────────
    result = conn.execute(text("""
        SELECT a.admission_id, a.department_id
        FROM admissions a
        JOIN doctors d ON a.admitting_doctor_id = d.doctor_id
        WHERE a.department_id != d.department_id
          AND d.specialty NOT IN (
            'Anesthesiologist','Hospitalist','Intensivist',
            'Radiologist','Pathologist'
          )
    """))
    rows    = result.fetchall()
    updates = []
    for row in rows:
        adm_id, dept_id = row
        docs = dept_doctor_map.get(dept_id, [])
        if docs:
            updates.append({
                "admission_id": adm_id,
                "doctor_id":    random.choice(docs)
            })

    batch_update(conn,
        "UPDATE admissions SET admitting_doctor_id = :doctor_id "
        "WHERE admission_id = :admission_id",
        updates
    )
    print(f"    Reassigned doctors for {len(updates)} admissions")

    # ── Room-department mismatch ───────────────────────────────────────────
    dept_room_map = get_dept_room_map(conn)

    result = conn.execute(text("""
        SELECT a.admission_id, a.department_id
        FROM admissions a
        JOIN rooms r ON a.room_id = r.room_id
        WHERE a.department_id != r.department_id
          AND a.room_id IS NOT NULL
    """))
    rows    = result.fetchall()
    updates = []
    for row in rows:
        adm_id, dept_id = row
        rooms = dept_room_map.get(dept_id, [])
        if rooms:
            updates.append({
                "admission_id": adm_id,
                "room_id":      random.choice(rooms)
            })

    batch_update(conn,
        "UPDATE admissions SET room_id = :room_id "
        "WHERE admission_id = :admission_id",
        updates
    )
    print(f"    Reassigned rooms for {len(updates)} admissions")

    # ── Condition-room mismatch ────────────────────────────────────────────
    result = conn.execute(text("""
        SELECT a.admission_id, a.patient_condition, a.department_id, r.room_type
        FROM admissions a
        JOIN rooms r ON a.room_id = r.room_id
        WHERE a.room_id IS NOT NULL AND (
            (a.patient_condition = 'Intensive' AND r.room_type NOT IN ('ICU','NICU'))
         OR (a.patient_condition = 'Maximum'   AND r.room_type NOT IN ('ICU','NICU','Private','Isolation'))
         OR (a.patient_condition = 'Moderate'  AND r.room_type NOT IN ('Standard','Private'))
         OR (a.patient_condition = 'Minimal'   AND r.room_type NOT IN ('Standard','Recovery','Private'))
        )
    """))
    rows    = result.fetchall()
    updates = []

    for row in rows:
        adm_id, condition, dept_id, room_type = row
        allowed_types = CONDITION_ROOM_MAP.get(condition, [])

        # Try to find an appropriate room in the same department
        placeholders = ', '.join(f"'{rt}'" for rt in allowed_types)
        new_room_row = conn.execute(text(f"""
            SELECT room_id FROM rooms
            WHERE department_id = :dept_id
              AND room_type IN ({placeholders})
            LIMIT 1
        """), {"dept_id": dept_id}).fetchone()

        if new_room_row:
            # Found a better room — reassign
            updates.append({
                "admission_id": adm_id,
                "room_id":      new_room_row[0],
                "condition":    None  # no condition change needed
            })
        else:
            # No appropriate room available — adjust condition to match room
            min_cond = ROOM_MIN_CONDITION.get(room_type, 'Minimal')
            updates.append({
                "admission_id": adm_id,
                "room_id":      None,   # no room change
                "condition":    min_cond
            })

    room_updates      = [u for u in updates if u["room_id"]      is not None]
    condition_updates = [u for u in updates if u["condition"] is not None]

    if room_updates:
        batch_update(conn,
            "UPDATE admissions SET room_id = :room_id "
            "WHERE admission_id = :admission_id",
            room_updates
        )
    if condition_updates:
        batch_update(conn,
            "UPDATE admissions SET patient_condition = :condition "
            "WHERE admission_id = :admission_id",
            condition_updates
        )
    print(f"    Fixed condition/room for {len(updates)} admissions "
          f"({len(room_updates)} room reassignments, "
          f"{len(condition_updates)} condition adjustments)")
    print("    Group 4 complete.")


# =============================================================================
# GROUP 5 — DIAGNOSIS-DEPARTMENT ALIGNMENT
# =============================================================================

def validate_diagnoses(conn) -> dict:
    male_codes   = "'" + "','".join(MALE_IMPOSSIBLE_CODES)   + "'"
    female_codes = "'" + "','".join(FEMALE_IMPOSSIBLE_CODES) + "'"
    newborn_codes= "'" + "','".join(NEWBORN_ONLY_CODES)      + "'"
    return {
        'male_impossible_codes': _count(conn, f"""
            SELECT COUNT(*) FROM diagnoses d
            JOIN admissions a ON d.admission_id = a.admission_id
            JOIN patients p ON a.patient_id = p.patient_id
            WHERE p.gender = 'M' AND d.icd10_code IN ({male_codes})
        """),
        'female_impossible_codes': _count(conn, f"""
            SELECT COUNT(*) FROM diagnoses d
            JOIN admissions a ON d.admission_id = a.admission_id
            JOIN patients p ON a.patient_id = p.patient_id
            WHERE p.gender = 'F' AND d.icd10_code IN ({female_codes})
        """),
        'newborn_codes_on_adults': _count(conn, f"""
            SELECT COUNT(*) FROM diagnoses d
            JOIN admissions a ON d.admission_id = a.admission_id
            JOIN patients p ON a.patient_id = p.patient_id
            WHERE p.age > 1 AND d.icd10_code IN ({newborn_codes})
        """),
    }


def repair_diagnoses(conn):
    print("  [Group 5] Repairing diagnosis alignment violations...")

    dept_map = get_dept_name_map(conn)

    def resample_diagnoses(where_clause: str, params: dict = {}):
        result = conn.execute(text(f"""
            SELECT d.diagnosis_id, a.department_id
            FROM diagnoses d
            JOIN admissions a ON d.admission_id = a.admission_id
            JOIN patients p ON a.patient_id = p.patient_id
            WHERE {where_clause}
        """), params)
        rows    = result.fetchall()
        updates = []
        for row in rows:
            dx_id, dept_id = row
            dept_name = dept_map.get(dept_id, 'Internal Medicine')
            new_dx    = sample_diagnosis(dept_name)
            # Resample until we get a code that isn't in any impossible set
            attempts = 0
            while (new_dx['icd10_code'] in MALE_IMPOSSIBLE_CODES
                   or new_dx['icd10_code'] in FEMALE_IMPOSSIBLE_CODES
                   or new_dx['icd10_code'] in NEWBORN_ONLY_CODES) and attempts < 10:
                new_dx   = sample_diagnosis(dept_name)
                attempts += 1
            updates.append({
                "diagnosis_id": dx_id,
                "icd10_code":   new_dx['icd10_code']
            })
        return updates

    male_codes    = "'" + "','".join(MALE_IMPOSSIBLE_CODES)   + "'"
    female_codes  = "'" + "','".join(FEMALE_IMPOSSIBLE_CODES) + "'"
    newborn_codes = "'" + "','".join(NEWBORN_ONLY_CODES)      + "'"

    u1 = resample_diagnoses(f"p.gender = 'M' AND d.icd10_code IN ({male_codes})")
    u2 = resample_diagnoses(f"p.gender = 'F' AND d.icd10_code IN ({female_codes})")
    u3 = resample_diagnoses(f"p.age > 1 AND d.icd10_code IN ({newborn_codes})")

    all_updates = u1 + u2 + u3
    batch_update(conn,
        "UPDATE diagnoses SET icd10_code = :icd10_code "
        "WHERE diagnosis_id = :diagnosis_id",
        all_updates
    )
    print(f"    Resampled {len(u1)} male-impossible, "
          f"{len(u2)} female-impossible, "
          f"{len(u3)} newborn-on-adult diagnoses")
    print("    Group 5 complete.")


# =============================================================================
# GROUP 6 — FINANCIAL CONSISTENCY
# =============================================================================

def validate_financial(conn) -> dict:
    return {
        'billing_amount_mismatch': _count(conn, """
            SELECT COUNT(*) FROM billing b
            JOIN (
                SELECT bill_id, ROUND(SUM(total_cost), 2) AS line_total
                FROM billing_line_items GROUP BY bill_id
            ) li ON b.bill_id = li.bill_id
            WHERE b.total_amount != li.line_total
        """),
        'denied_with_coverage': _count(conn, """
            SELECT COUNT(*) FROM billing
            WHERE payment_status = 'Denied' AND insurance_covered > 0
        """),
        'writeoff_with_patient_resp': _count(conn, """
            SELECT COUNT(*) FROM billing
            WHERE payment_status = 'Write-Off' AND patient_responsibility > 0
        """),
        'paid_missing_payment_date': _count(conn, """
            SELECT COUNT(*) FROM billing
            WHERE payment_status = 'Paid' AND payment_date IS NULL
        """),
        'unpaid_has_payment_date': _count(conn, """
            SELECT COUNT(*) FROM billing
            WHERE payment_status IN ('Pending','Denied','Write-Off')
              AND payment_date IS NOT NULL
        """),
    }


def repair_financial(conn):
    print("  [Group 6] Repairing financial violations...")

    # ── Reconcile billing total to sum of line items ───────────────────────
    conn.execute(text("""
        UPDATE billing b
        JOIN (
            SELECT bill_id, ROUND(SUM(total_cost), 2) AS line_total
            FROM billing_line_items GROUP BY bill_id
        ) li ON b.bill_id = li.bill_id
        JOIN payers p ON b.payer_id = p.payer_id
        SET
            b.total_amount = li.line_total,
            b.insurance_covered = ROUND(li.line_total *
                CASE p.payer_type
                    WHEN 'Medicare'             THEN 0.80
                    WHEN 'Medicaid'             THEN 0.72
                    WHEN 'Private Insurance'    THEN 0.85
                    WHEN 'Self-Pay'             THEN 0.00
                    WHEN 'Workers Compensation' THEN 0.90
                    WHEN 'CHIP'                 THEN 0.75
                    ELSE 0.00 END, 2),
            b.patient_responsibility = ROUND(li.line_total -
                (li.line_total *
                CASE p.payer_type
                    WHEN 'Medicare'             THEN 0.80
                    WHEN 'Medicaid'             THEN 0.72
                    WHEN 'Private Insurance'    THEN 0.85
                    WHEN 'Self-Pay'             THEN 0.00
                    WHEN 'Workers Compensation' THEN 0.90
                    WHEN 'CHIP'                 THEN 0.75
                    ELSE 0.00 END), 2)
        WHERE b.total_amount != li.line_total
    """))

    # ── Denied: zero out insurance coverage ───────────────────────────────
    conn.execute(text("""
        UPDATE billing
        SET insurance_covered      = 0.00,
            patient_responsibility = total_amount
        WHERE payment_status = 'Denied'
    """))

    # ── Write-Off: zero out patient responsibility ─────────────────────────
    conn.execute(text("""
        UPDATE billing
        SET patient_responsibility = 0.00
        WHERE payment_status = 'Write-Off'
    """))

    # ── Paid: ensure payment_date is set ──────────────────────────────────
    conn.execute(text("""
        UPDATE billing
        SET payment_date = DATE_ADD(bill_date, INTERVAL FLOOR(5 + RAND() * 85) DAY)
        WHERE payment_status = 'Paid' AND payment_date IS NULL
    """))

    # ── Pending/Denied/Write-Off: clear payment_date ──────────────────────
    conn.execute(text("""
        UPDATE billing
        SET payment_date = NULL
        WHERE payment_status IN ('Pending','Denied','Write-Off')
    """))

    print("    Group 6 complete.")


# =============================================================================
# MAIN VALIDATE / REPAIR FUNCTIONS
# =============================================================================

def validate_all(conn) -> dict:
    """
    Run all validation checks and return a structured report.
    Does not modify any data.
    """
    return {
        'group1_temporal':        validate_temporal(conn),
        'group2_age':             validate_age(conn),
        'group3_admission_type':  validate_admission_type(conn),
        'group4_department':      validate_department(conn),
        'group5_diagnoses':       validate_diagnoses(conn),
        'group6_financial':       validate_financial(conn),
    }


def print_report(report: dict):
    """Print a human-readable validation report."""
    group_labels = {
        'group1_temporal':       'Group 1 — Temporal',
        'group2_age':            'Group 2 — Age-based',
        'group3_admission_type': 'Group 3 — Admission Type',
        'group4_department':     'Group 4 — Department Consistency',
        'group5_diagnoses':      'Group 5 — Diagnosis Alignment',
        'group6_financial':      'Group 6 — Financial',
    }

    total_violations = 0
    print(f"\n{'='*60}")
    print("  Validation Report")
    print(f"{'='*60}")

    for group_key, checks in report.items():
        group_total = sum(checks.values())
        total_violations += group_total
        status = "✓ clean" if group_total == 0 else f"✗ {group_total:,} violations"
        print(f"\n  {group_labels.get(group_key, group_key)} — {status}")
        for rule, count in checks.items():
            flag = "    ✓" if count == 0 else "    ✗"
            print(f"    {flag}  {rule:<45} {count:>6,}")

    print(f"\n{'='*60}")
    print(f"  Total violations: {total_violations:,}")
    print(f"{'='*60}\n")


def repair_all(conn):
    """
    Apply all repairs in the correct dependency sequence.
    Group 1 must run before all others.
    Group 6 must run last.
    """
    print(f"\n{'='*60}")
    print("  Running repairs...")
    print(f"{'='*60}\n")
    repair_temporal(conn)
    conn.commit()
    repair_age(conn)
    conn.commit()
    repair_admission_type(conn)
    conn.commit()
    repair_department(conn)
    conn.commit()
    repair_diagnoses(conn)
    conn.commit()
    repair_financial(conn)
    conn.commit()
    print(f"\n{'='*60}")
    print("  All repairs complete.")
    print(f"{'='*60}\n")


def run_repair(engine=None):
    """
    Full generate-validate-repair cycle entry point.

    If engine is None, creates one from DB_URL.
    Prints a before/after validation report.
    """
    if engine is None:
        engine = create_engine(DB_URL, echo=False)

    print("\n--- Pre-repair validation ---")
    with engine.connect() as conn:
        before = validate_all(conn)
    print_report(before)

    with engine.connect() as conn:
        repair_all(conn)

    print("\n--- Post-repair validation ---")
    with engine.connect() as conn:
        after = validate_all(conn)
    print_report(after)
