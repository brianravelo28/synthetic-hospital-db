"""
hospital_generator.py  (constraint-aware)
================================================
Synthetic data generator for hospital_db.
Populates all 17 tables in topological dependency order.

What "constraint-aware" means here — each item exists to avoid a specific
class of violation caught by src/validate_repair.py (history and measured
results: docs/METHODOLOGY.md):

  Round one (groups 1-6 of the validator)
    - Admission department & type are driven by patient age.
    - Room is chosen to suit the patient's condition.
    - Diagnoses are department-filtered and never gender/age-impossible.
    - Every department gets at least one doctor (and one room).

  Round two (group 7, the independent realism checks)
    - Admission status follows from dates: a stay that hasn't ended is
      "Admitted"; "Scheduled" admissions are in the future; nothing is
      admitted before the patient was born (newborns are admitted at birth,
      and only once).
    - Only admissions that actually happened get clinical records.
    - Staff only act after their hire date (StaffPool), shifts are in their
      own department, hires respect a minimum age.
    - Triage vitals are age-banded.
    - Bills exist only for discharged admissions and are built bottom-up from
      that admission's own room stay, procedures, tests and medications, so
      line items belong to the bill's admission and the total is their sum.

Still left to repair (true edge cases):
  - registered_date for newborn patients (patients are generated before
    admissions exist, so it can't be known at patient-creation time).
  - condition/room mismatches in departments with no room of a suitable type
    (falls back to any room in-department; repair downgrades the condition).

Not modelled: clinical coherence between diagnoses, procedures and
medications (drawn independently), or a real population/occupancy curve.

Prerequisites:
    pip install -r requirements.txt
    MySQL/MariaDB running with the hospital_db schema loaded (hospital_db.sql)
    icd10_diagnoses.py in the same directory
    connection string from HOSPITAL_DB_URL (default: root, no password, localhost)

Usage:
    python src/run_pipeline.py --size large        # the whole pipeline
  or, from a notebook:
    exec(open('hospital_generator.py').read())
    main('small')   # or 'medium' / 'large'
"""

import os
import sys
import random
import numpy as np
import pandas as pd
from faker import Faker
from faker.providers import ssn as ssn_provider, BaseProvider, person as person_provider
from bisect import bisect_right
from datetime import date, datetime, timedelta, time as dtime
from sqlalchemy import create_engine, text
from collections import defaultdict

from icd10_diagnoses import sample_diagnosis
from shared_rules import (
    AS_OF, CONDITION_ROOM_MAP, FEMALE_IMPOSSIBLE_CODES, MALE_IMPOSSIBLE_CODES,
    NEWBORN_ONLY_CODES, OB_NEWBORN_DEPTS, PAYER_COVERAGE,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

DB_URL = os.environ.get("HOSPITAL_DB_URL", "mysql+pymysql://root:@localhost/hospital_db")

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
Faker.seed(SEED)

fake = Faker(["en_US"])
fake.add_provider(ssn_provider)
fake.add_provider(BaseProvider)
fake.add_provider(person_provider)

HOSPITAL_SIZES = {
    "small": {
        "description":       "Small community hospital (~50 beds)",
        "patients":           500,
        "doctors":             25,
        "nurses":              60,
        "employees":           40,
        "rooms":               55,
        "admissions":         800,
        "avg_diagnoses":      1.5,
        "avg_procedures":     0.7,
        "avg_medications":    1.2,
        "avg_tests":          0.9,
        "shifts_per_staff":   8,
    },
    "medium": {
        "description":       "Mid-size regional hospital (~200 beds)",
        "patients":          2000,
        "doctors":            100,
        "nurses":             250,
        "employees":          150,
        "rooms":              220,
        "admissions":        3200,
        "avg_diagnoses":      1.7,
        "avg_procedures":     0.9,
        "avg_medications":    1.5,
        "avg_tests":          1.2,
        "shifts_per_staff":  10,
    },
    "large": {
        "description":       "Large academic medical center (~500+ beds)",
        "patients":          8000,
        "doctors":            350,
        "nurses":             900,
        "employees":          500,
        "rooms":              560,
        "admissions":       12000,
        "avg_diagnoses":      2.0,
        "avg_procedures":     1.2,
        "avg_medications":    1.8,
        "avg_tests":          1.5,
        "shifts_per_staff":  12,
    }
}


# =============================================================================
# STATIC REFERENCE DATA
# =============================================================================

DEPARTMENTS_DATA = [
    {"department_id": "DEP-001", "dep_name": "Emergency Medicine",  "floor_number": 1, "bed_capacity": 20},
    {"department_id": "DEP-002", "dep_name": "Intensive Care",      "floor_number": 2, "bed_capacity": 15},
    {"department_id": "DEP-003", "dep_name": "Cardiology",          "floor_number": 3, "bed_capacity": 25},
    {"department_id": "DEP-004", "dep_name": "General Surgery",     "floor_number": 2, "bed_capacity": 20},
    {"department_id": "DEP-005", "dep_name": "Internal Medicine",   "floor_number": 4, "bed_capacity": 30},
    {"department_id": "DEP-006", "dep_name": "Neurology",           "floor_number": 4, "bed_capacity": 20},
    {"department_id": "DEP-007", "dep_name": "Orthopedic",          "floor_number": 3, "bed_capacity": 20},
    {"department_id": "DEP-008", "dep_name": "Pediatrics",          "floor_number": 5, "bed_capacity": 25},
    {"department_id": "DEP-009", "dep_name": "OB/GYN",              "floor_number": 5, "bed_capacity": 20},
    {"department_id": "DEP-010", "dep_name": "Oncology",            "floor_number": 6, "bed_capacity": 20},
    {"department_id": "DEP-011", "dep_name": "Gastroenterology",    "floor_number": 3, "bed_capacity": 15},
    {"department_id": "DEP-012", "dep_name": "Radiology",           "floor_number": 1, "bed_capacity":  5},
    {"department_id": "DEP-013", "dep_name": "Psychiatry",          "floor_number": 6, "bed_capacity": 20},
    {"department_id": "DEP-014", "dep_name": "Urology",             "floor_number": 3, "bed_capacity": 15},
    {"department_id": "DEP-015", "dep_name": "Geriatric",           "floor_number": 4, "bed_capacity": 20},
    {"department_id": "DEP-016", "dep_name": "Hematology",          "floor_number": 6, "bed_capacity": 15},
    {"department_id": "DEP-017", "dep_name": "Endocrinology",       "floor_number": 4, "bed_capacity": 10},
    {"department_id": "DEP-018", "dep_name": "Anesthesiology",      "floor_number": 2, "bed_capacity":  5},
    {"department_id": "DEP-019", "dep_name": "Pathology",           "floor_number": 1, "bed_capacity":  3},
    {"department_id": "DEP-020", "dep_name": "Operations",          "floor_number": 2, "bed_capacity": 15},
]

PAYERS_DATA = [
    {"payer_id": "PAY-001", "payer_name": "Medicare",                     "payer_type": "Medicare",             "contact_phone": "1-800-633-4227"},
    {"payer_id": "PAY-002", "payer_name": "Medicaid Florida",             "payer_type": "Medicaid",             "contact_phone": "1-877-711-3662"},
    {"payer_id": "PAY-003", "payer_name": "Blue Cross Blue Shield",       "payer_type": "Private Insurance",    "contact_phone": "1-800-521-2227"},
    {"payer_id": "PAY-004", "payer_name": "Aetna Health",                 "payer_type": "Private Insurance",    "contact_phone": "1-800-872-3862"},
    {"payer_id": "PAY-005", "payer_name": "UnitedHealthcare",             "payer_type": "Private Insurance",    "contact_phone": "1-866-414-1959"},
    {"payer_id": "PAY-006", "payer_name": "Cigna Healthcare",             "payer_type": "Private Insurance",    "contact_phone": "1-800-244-6224"},
    {"payer_id": "PAY-007", "payer_name": "Self-Pay",                     "payer_type": "Self-Pay",             "contact_phone": None},
    {"payer_id": "PAY-008", "payer_name": "Florida Workers Compensation", "payer_type": "Workers Compensation", "contact_phone": "1-800-742-2214"},
    {"payer_id": "PAY-009", "payer_name": "CHIP Florida",                 "payer_type": "CHIP",                 "contact_phone": "1-888-540-5437"},
    {"payer_id": "PAY-010", "payer_name": "Humana",                       "payer_type": "Private Insurance",    "contact_phone": "1-800-448-6262"},
]

PROCEDURES_DATA = [
    {"procedure_id": "PRC-001", "procedure_code": "99283", "procedure_name": "Emergency department visit, moderate severity",    "department_id": "DEP-001", "base_cost":   850.00, "duration_minutes":  60},
    {"procedure_id": "PRC-002", "procedure_code": "31500", "procedure_name": "Endotracheal intubation",                         "department_id": "DEP-001", "base_cost":  1200.00, "duration_minutes":  30},
    {"procedure_id": "PRC-003", "procedure_code": "36556", "procedure_name": "Central venous catheter placement",               "department_id": "DEP-002", "base_cost":  2100.00, "duration_minutes":  45},
    {"procedure_id": "PRC-004", "procedure_code": "94002", "procedure_name": "Mechanical ventilation management",               "department_id": "DEP-002", "base_cost":   900.00, "duration_minutes": None},
    {"procedure_id": "PRC-005", "procedure_code": "93306", "procedure_name": "Echocardiogram with Doppler",                     "department_id": "DEP-003", "base_cost":  1500.00, "duration_minutes":  60},
    {"procedure_id": "PRC-006", "procedure_code": "93454", "procedure_name": "Coronary artery angiography",                    "department_id": "DEP-003", "base_cost":  8500.00, "duration_minutes":  90},
    {"procedure_id": "PRC-007", "procedure_code": "92960", "procedure_name": "Cardioversion, elective",                        "department_id": "DEP-003", "base_cost":  1800.00, "duration_minutes":  30},
    {"procedure_id": "PRC-008", "procedure_code": "33533", "procedure_name": "Coronary artery bypass graft",                   "department_id": "DEP-020", "base_cost": 42000.00, "duration_minutes": 240},
    {"procedure_id": "PRC-009", "procedure_code": "44950", "procedure_name": "Appendectomy",                                   "department_id": "DEP-004", "base_cost":  7500.00, "duration_minutes":  90},
    {"procedure_id": "PRC-010", "procedure_code": "47562", "procedure_name": "Laparoscopic cholecystectomy",                   "department_id": "DEP-004", "base_cost":  9000.00, "duration_minutes":  75},
    {"procedure_id": "PRC-011", "procedure_code": "49505", "procedure_name": "Inguinal hernia repair",                         "department_id": "DEP-004", "base_cost":  6200.00, "duration_minutes":  60},
    {"procedure_id": "PRC-012", "procedure_code": "71046", "procedure_name": "Chest X-ray, 2 views",                           "department_id": "DEP-012", "base_cost":   220.00, "duration_minutes":  15},
    {"procedure_id": "PRC-013", "procedure_code": "74177", "procedure_name": "CT scan abdomen and pelvis with contrast",       "department_id": "DEP-012", "base_cost":  1800.00, "duration_minutes":  30},
    {"procedure_id": "PRC-014", "procedure_code": "70553", "procedure_name": "MRI brain with and without contrast",            "department_id": "DEP-012", "base_cost":  2400.00, "duration_minutes":  60},
    {"procedure_id": "PRC-015", "procedure_code": "78452", "procedure_name": "Myocardial perfusion imaging",                   "department_id": "DEP-012", "base_cost":  3100.00, "duration_minutes":  90},
    {"procedure_id": "PRC-016", "procedure_code": "95819", "procedure_name": "Electroencephalogram (EEG)",                     "department_id": "DEP-006", "base_cost":   900.00, "duration_minutes":  60},
    {"procedure_id": "PRC-017", "procedure_code": "62270", "procedure_name": "Lumbar puncture (spinal tap)",                   "department_id": "DEP-006", "base_cost":  1100.00, "duration_minutes":  30},
    {"procedure_id": "PRC-018", "procedure_code": "27130", "procedure_name": "Total hip arthroplasty",                         "department_id": "DEP-007", "base_cost": 22000.00, "duration_minutes": 150},
    {"procedure_id": "PRC-019", "procedure_code": "27447", "procedure_name": "Total knee arthroplasty",                        "department_id": "DEP-007", "base_cost": 20000.00, "duration_minutes": 120},
    {"procedure_id": "PRC-020", "procedure_code": "27236", "procedure_name": "Open reduction internal fixation, femoral neck", "department_id": "DEP-007", "base_cost": 15000.00, "duration_minutes": 120},
    {"procedure_id": "PRC-021", "procedure_code": "59400", "procedure_name": "Routine obstetric care, vaginal delivery",       "department_id": "DEP-009", "base_cost":  5500.00, "duration_minutes": None},
    {"procedure_id": "PRC-022", "procedure_code": "59510", "procedure_name": "Routine obstetric care, cesarean delivery",      "department_id": "DEP-009", "base_cost":  9500.00, "duration_minutes":  90},
    {"procedure_id": "PRC-023", "procedure_code": "45378", "procedure_name": "Colonoscopy, diagnostic",                       "department_id": "DEP-011", "base_cost":  1800.00, "duration_minutes":  45},
    {"procedure_id": "PRC-024", "procedure_code": "43239", "procedure_name": "Upper GI endoscopy with biopsy",                "department_id": "DEP-011", "base_cost":  1500.00, "duration_minutes":  30},
    {"procedure_id": "PRC-025", "procedure_code": "96413", "procedure_name": "Chemotherapy administration, IV infusion",       "department_id": "DEP-010", "base_cost":  2200.00, "duration_minutes": 120},
    {"procedure_id": "PRC-026", "procedure_code": "77373", "procedure_name": "Stereotactic body radiation therapy",            "department_id": "DEP-010", "base_cost":  5000.00, "duration_minutes":  60},
    {"procedure_id": "PRC-027", "procedure_code": "52310", "procedure_name": "Cystoscopy with removal of ureteral stone",      "department_id": "DEP-014", "base_cost":  4500.00, "duration_minutes":  45},
    {"procedure_id": "PRC-028", "procedure_code": "90837", "procedure_name": "Psychotherapy, 60 minutes",                     "department_id": "DEP-013", "base_cost":   250.00, "duration_minutes":  60},
    {"procedure_id": "PRC-029", "procedure_code": "99232", "procedure_name": "Subsequent hospital care, moderate complexity",  "department_id": "DEP-005", "base_cost":   420.00, "duration_minutes":  30},
    {"procedure_id": "PRC-030", "procedure_code": "36430", "procedure_name": "Blood transfusion",                             "department_id": "DEP-002", "base_cost":  1100.00, "duration_minutes":  90},
]

DOCTOR_SPECIALTIES = [
    'Neurologist', 'Cardiologist', 'Urologist', 'Gynecologist', 'Obstetrician',
    'Pediatrician', 'Perinatologist', 'Neonatologist', 'Anesthesiologist', 'Neurosurgeon',
    'Cardiothoracic Surgeon', 'Intensivist', 'Emergency Medicine', 'General Surgeon',
    'Trauma Surgeon', 'Gastroenterologist', 'Pulmonologist', 'Otolaryngologist',
    'Ophthalmologist', 'Oncologist', 'Radiologist', 'Pathologist', 'Hematologist',
    'Colorectal Surgeon', 'Hospitalist', 'Endocrinologist', 'Psychiatrist',
    'Rheumatologist', 'Immunologist', 'Orthopedic Surgeon', 'Vascular Surgeon', 'Internist'
]

SPECIALTY_TO_DEPARTMENT = {
    'Neurologist':            ['DEP-006', 'DEP-008', 'DEP-015'],
    'Cardiologist':           ['DEP-003', 'DEP-015', 'DEP-020', 'DEP-002', 'DEP-008'],
    'Urologist':              ['DEP-014', 'DEP-020', 'DEP-015', 'DEP-002', 'DEP-008'],
    'Gynecologist':           ['DEP-009', 'DEP-020', 'DEP-002', 'DEP-015', 'DEP-008'],
    'Obstetrician':           ['DEP-009', 'DEP-020', 'DEP-002', 'DEP-008'],
    'Pediatrician':           ['DEP-008', 'DEP-001', 'DEP-005', 'DEP-020'],
    'Perinatologist':         ['DEP-009', 'DEP-020', 'DEP-002', 'DEP-008'],
    'Neonatologist':          ['DEP-008', 'DEP-002', 'DEP-020'],
    'Anesthesiologist':       ['DEP-018', 'DEP-001', 'DEP-020', 'DEP-002', 'DEP-005'],
    'Neurosurgeon':           ['DEP-020', 'DEP-002', 'DEP-006'],
    'Cardiothoracic Surgeon': ['DEP-020', 'DEP-002', 'DEP-003'],
    'Intensivist':            ['DEP-002', 'DEP-001', 'DEP-005', 'DEP-015'],
    'Emergency Medicine':     ['DEP-001', 'DEP-005', 'DEP-002', 'DEP-008'],
    'General Surgeon':        ['DEP-004', 'DEP-020', 'DEP-002'],
    'Trauma Surgeon':         ['DEP-001', 'DEP-002', 'DEP-020'],
    'Gastroenterologist':     ['DEP-011', 'DEP-020', 'DEP-002', 'DEP-015'],
    'Pulmonologist':          ['DEP-002', 'DEP-005', 'DEP-001', 'DEP-015'],
    'Otolaryngologist':       ['DEP-020', 'DEP-002', 'DEP-008'],
    'Ophthalmologist':        ['DEP-020', 'DEP-015', 'DEP-002'],
    'Oncologist':             ['DEP-010', 'DEP-020', 'DEP-015', 'DEP-002'],
    'Radiologist':            ['DEP-012', 'DEP-001', 'DEP-020'],
    'Pathologist':            ['DEP-019', 'DEP-005', 'DEP-020'],
    'Hematologist':           ['DEP-016', 'DEP-020', 'DEP-002'],
    'Colorectal Surgeon':     ['DEP-004', 'DEP-020', 'DEP-002'],
    'Hospitalist':            ['DEP-005', 'DEP-001', 'DEP-020'],
    'Endocrinologist':        ['DEP-017', 'DEP-020', 'DEP-002'],
    'Psychiatrist':           ['DEP-013'],
    'Rheumatologist':         ['DEP-015', 'DEP-005', 'DEP-020'],
    'Immunologist':           ['DEP-005', 'DEP-002', 'DEP-008'],
    'Orthopedic Surgeon':     ['DEP-007', 'DEP-002', 'DEP-020'],
    'Vascular Surgeon':       ['DEP-003', 'DEP-005', 'DEP-020'],
    'Internist':              ['DEP-005', 'DEP-015', 'DEP-020', 'DEP-002'],
}

NURSE_POSITIONS = [
    'LPN', 'RN', 'Med-Surgical', 'ER', 'Oncology Nurse', 'Nurse Administrator',
    'Nurse Educator', 'Nurse Informaticist', 'CRNA', 'Midwife', 'Nurse Practitioner'
]

NURSE_POSITION_TO_DEPARTMENT = {
    'LPN':                  None,
    'RN':                   None,
    'Med-Surgical':         ['DEP-001', 'DEP-002', 'DEP-020', 'DEP-004'],
    'ER':                   ['DEP-001'],
    'Oncology Nurse':       ['DEP-010'],
    'Nurse Administrator':  None,
    'Nurse Educator':       None,
    'Nurse Informaticist':  None,
    'CRNA':                 ['DEP-018', 'DEP-001', 'DEP-020', 'DEP-002'],
    'Midwife':              ['DEP-009'],
    'Nurse Practitioner':   None,
}

EMPLOYEE_POSITIONS = [
    'Billing Specialist', 'Medical Coder', 'Patient Services Coordinator',
    'Health Information Manager', 'Hospital Administrator', 'IT Analyst',
    'Facilities Manager', 'HR Coordinator', 'Medical Receptionist',
    'Supply Chain Coordinator', 'Quality Assurance Analyst', 'Compliance Officer'
]

MEDICATIONS_LIST = [
    {"drug_name": "Metoprolol",              "dosage": "50mg",       "frequency": "BID"},
    {"drug_name": "Lisinopril",              "dosage": "10mg",       "frequency": "QD"},
    {"drug_name": "Atorvastatin",            "dosage": "40mg",       "frequency": "QD"},
    {"drug_name": "Warfarin",                "dosage": "5mg",        "frequency": "QD"},
    {"drug_name": "Heparin",                 "dosage": "5000 units", "frequency": "TID"},
    {"drug_name": "Furosemide",              "dosage": "40mg",       "frequency": "BID"},
    {"drug_name": "Digoxin",                 "dosage": "0.125mg",    "frequency": "QD"},
    {"drug_name": "Amiodarone",              "dosage": "200mg",      "frequency": "TID"},
    {"drug_name": "Metformin",               "dosage": "500mg",      "frequency": "BID"},
    {"drug_name": "Insulin Glargine",        "dosage": "20 units",   "frequency": "QD"},
    {"drug_name": "Insulin Regular",         "dosage": "10 units",   "frequency": "TID"},
    {"drug_name": "Amoxicillin",             "dosage": "500mg",      "frequency": "TID"},
    {"drug_name": "Ciprofloxacin",           "dosage": "500mg",      "frequency": "BID"},
    {"drug_name": "Vancomycin",              "dosage": "1g",         "frequency": "BID"},
    {"drug_name": "Ceftriaxone",             "dosage": "1g",         "frequency": "QD"},
    {"drug_name": "Piperacillin-Tazobactam", "dosage": "3.375g",     "frequency": "QID"},
    {"drug_name": "Azithromycin",            "dosage": "500mg",      "frequency": "QD"},
    {"drug_name": "Acetaminophen",           "dosage": "650mg",      "frequency": "QID"},
    {"drug_name": "Ibuprofen",               "dosage": "400mg",      "frequency": "TID"},
    {"drug_name": "Morphine",                "dosage": "4mg",        "frequency": "PRN"},
    {"drug_name": "Hydrocodone",             "dosage": "5mg",        "frequency": "PRN"},
    {"drug_name": "Ketorolac",               "dosage": "30mg",       "frequency": "QID"},
    {"drug_name": "Omeprazole",              "dosage": "20mg",       "frequency": "QD"},
    {"drug_name": "Ondansetron",             "dosage": "4mg",        "frequency": "PRN"},
    {"drug_name": "Metoclopramide",          "dosage": "10mg",       "frequency": "TID"},
    {"drug_name": "Albuterol",               "dosage": "2.5mg",      "frequency": "PRN"},
    {"drug_name": "Ipratropium",             "dosage": "0.5mg",      "frequency": "QID"},
    {"drug_name": "Prednisone",              "dosage": "40mg",       "frequency": "QD"},
    {"drug_name": "Dexamethasone",           "dosage": "6mg",        "frequency": "QD"},
    {"drug_name": "Lorazepam",               "dosage": "1mg",        "frequency": "PRN"},
    {"drug_name": "Levetiracetam",           "dosage": "500mg",      "frequency": "BID"},
    {"drug_name": "Haloperidol",             "dosage": "2mg",        "frequency": "PRN"},
    {"drug_name": "Sertraline",              "dosage": "50mg",       "frequency": "QD"},
]

ADMISSION_TYPES  = ['Emergency', 'Elective', 'Urgent', 'Newborn', 'Scheduled']
ADMISSION_TYPE_P = [0.30, 0.25, 0.25, 0.08, 0.12]

# Each admission is drawn as one of three categories. "Admitted" vs "Discharged"
# is then decided by the dates: a stay that hasn't ended by now is still
# in progress (Admitted) — it is not a coin flip, so the census stays small
# and recent instead of containing stays that began in 2020.
ADMISSION_CATEGORIES = ['Scheduled', 'Cancelled', 'Completed']
ADMISSION_CATEGORY_P = [0.05, 0.05, 0.90]
SCHEDULED_TYPES      = ['Scheduled', 'Elective']
SCHEDULED_TYPE_P     = [0.50, 0.50]
MAX_STAY_DAYS        = 45

DISCHARGE_DISPOSITIONS = {
    'options': ['Home', 'Transfer', 'Skilled Nursing Facility', 'Deceased', 'AMA'],
    'probs':   [0.70, 0.10, 0.10, 0.05, 0.05],
}

ROOM_TYPES  = ['Standard', 'Private', 'ICU', 'NICU', 'OR', 'ER', 'Recovery', 'Isolation']
ROOM_TYPE_P = [0.35, 0.20, 0.15, 0.05, 0.10, 0.05, 0.05, 0.05]

SHIFT_TYPES = ['Morning', 'Afternoon', 'Night']

CHIEF_COMPLAINTS = [
    'Chest pain', 'Shortness of breath', 'Abdominal pain', 'Fever',
    'Nausea and vomiting', 'Headache', 'Back pain', 'Dizziness',
    'Weakness', 'Altered mental status', 'Syncope', 'Palpitations',
    'Cough', 'Leg pain', 'Trauma'
]

# ── Age → department/admission-type pools ──────────────────────────────────
# Keeps admissions rule-safe against validate_repair.py Group 2 checks:
#   newborn_wrong_age / newborn_wrong_dept / pediatric_in_geriatric_dept /
#   adult_in_pediatric_dept
NEWBORN_DEPT_POOL   = sorted(OB_NEWBORN_DEPTS)
PEDIATRIC_DEPT_POOL = ['DEP-008', 'DEP-001', 'DEP-002']

NEWBORN_ADM_TYPES   = ['Newborn', 'Emergency', 'Urgent']
NEWBORN_ADM_TYPE_P  = [0.60, 0.25, 0.15]
# a patient can only be born once, so only their first admission can be 'Newborn'
NEWBORN_REPEAT_TYPES  = ['Emergency', 'Urgent']
NEWBORN_REPEAT_TYPE_P = [0.625, 0.375]

_non_newborn_pairs   = [(t, p) for t, p in zip(ADMISSION_TYPES, ADMISSION_TYPE_P) if t != 'Newborn']
NON_NEWBORN_TYPES    = [t for t, _ in _non_newborn_pairs]
_non_newborn_p_raw   = np.array([p for _, p in _non_newborn_pairs])
NON_NEWBORN_TYPE_P   = list(_non_newborn_p_raw / _non_newborn_p_raw.sum())

# CONDITION_ROOM_MAP, the impossible-diagnosis code sets, PAYER_COVERAGE and
# OB_NEWBORN_DEPTS are shared with the validator: see shared_rules.py.


# =============================================================================
# HELPERS
# =============================================================================

def gen_id(prefix: str) -> str:
    return f"{prefix}-{fake.unique.random_int(min=100000, max=999999)}"


def random_date_between(start: date, end: date) -> date:
    if end < start:
        end = start
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta, 0)))


def random_datetime_between(start: datetime, end: datetime) -> datetime:
    if end < start:
        end = start + timedelta(hours=1)
    seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, max(seconds, 1)))


def date_within_admission(adm_dt: datetime, dis_dt: datetime = None) -> date:
    """Return a random date between admission and discharge (or today)."""
    start = adm_dt.date() if isinstance(adm_dt, datetime) else adm_dt
    end   = dis_dt.date() if dis_dt else AS_OF.date()
    return random_date_between(start, end)


def datetime_within_admission(adm_dt: datetime, dis_dt: datetime = None) -> datetime:
    """Return a random datetime between admission and discharge (or now)."""
    end = dis_dt if dis_dt else AS_OF
    return random_datetime_between(adm_dt, end)


def gender_name(gender: str) -> str:
    if gender == 'M':
        return fake.first_name_male()
    elif gender == 'F':
        return fake.first_name_female()
    return fake.first_name_nonbinary()


def age_from_dob(dob: date) -> int:
    return int((AS_OF.date() - dob).days / 365.2425)


def poisson_count(avg: float) -> int:
    return max(0, np.random.poisson(avg))


def execute_batch(conn, sql: str, rows: list):
    if rows:
        conn.execute(text(sql), rows)


# Rough skew of an inpatient population toward older ages (not a real
# population curve — see docs/METHODOLOGY.md): (min_age, max_age, weight)
AGE_BANDS = [(0, 0, 0.015), (1, 17, 0.135), (18, 39, 0.200), (40, 64, 0.300), (65, 100, 0.350)]


def sample_birth_date() -> date:
    lo, hi, _ = random.choices(AGE_BANDS, weights=[w for _, _, w in AGE_BANDS])[0]
    age = random.randint(lo, hi)
    return AS_OF.date() - timedelta(days=int(age * 365.2425) + 1 + random.randint(0, 363))


def hire_date_for(birth: date, hire_start: date, min_age_years: int, latest: date = None) -> date:
    """A hire date no earlier than `min_age_years` after birth (plus a small margin)."""
    earliest = max(hire_start, birth + timedelta(days=int(min_age_years * 365.25) + 3))
    return random_date_between(earliest, latest or AS_OF.date())


class StaffPool:
    """
    Staff sorted by hire date, so an event can only be assigned to someone who
    had already been hired on the event's date (and, optionally, who works in a
    given department).
    """

    def __init__(self, rows):                  # rows: [(staff_id, hire_date, department_id)]
        self.rows  = sorted(rows, key=lambda r: r[1])
        self.dates = [r[1] for r in self.rows]
        self.by_dept = defaultdict(list)
        for r in self.rows:
            self.by_dept[r[2]].append(r)
        self.dept_dates = {d: [r[1] for r in rs] for d, rs in self.by_dept.items()}

    def _scope(self, dept):
        if dept and self.by_dept.get(dept):
            return self.by_dept[dept], self.dept_dates[dept]
        return self.rows, self.dates

    def pick(self, on_date, dept=None) -> str:
        if isinstance(on_date, datetime):
            on_date = on_date.date()
        rows, dates = self._scope(dept)
        n = bisect_right(dates, on_date)
        return random.choice(rows[:n] if n else rows[:1])[0]

    def pick_with_date(self, on_dt: datetime, dept):
        """Pick a department member hired by `on_dt`; if none was yet, use the
        earliest hire and push the date forward to their start."""
        rows, dates = self._scope(dept)
        n = bisect_right(dates, on_dt.date())
        if n:
            return random.choice(rows[:n])[0], on_dt
        return rows[0][0], max(on_dt, datetime.combine(rows[0][1], dtime(8, 0)))


def _vitals_for_age(age: int) -> dict:
    """Plausible (min, max) ranges by age band: height cm, weight kg, HR, RR, BP."""
    if age <= 1:
        return dict(h=(45, 80),   w=(2.5, 11),  hr=(100, 160), rr=(30, 53), sbp=(70, 100),  dbp=(40, 65))
    if age <= 12:
        return dict(h=(85, 155),  w=(12, 50),   hr=(70, 130),  rr=(18, 30), sbp=(90, 120),  dbp=(55, 80))
    if age <= 17:
        return dict(h=(150, 190), w=(40, 90),   hr=(55, 110),  rr=(12, 22), sbp=(100, 135), dbp=(60, 85))
    return dict(h=(140, 200),     w=(45, 150),  hr=(50, 140),  rr=(12, 28), sbp=(90, 180),  dbp=(50, 110))


# room_type -> (min, max daily rate, bill description)
ROOM_RATES = {
    'Standard':  (800, 1400,  'Standard Room (per day)'),
    'Private':   (1200, 2000, 'Private Room (per day)'),
    'ICU':       (2500, 3500, 'ICU Room (per day)'),
    'NICU':      (2500, 3500, 'NICU Bed (per day)'),
    'OR':        (2000, 3000, 'Operating Room Recovery (per day)'),
    'ER':        (800, 1200,  'ER Bay (per visit)'),
    'Recovery':  (1000, 1600, 'Recovery Room (per day)'),
    'Isolation': (1500, 2200, 'Isolation Room (per day)'),
}


def _sample_valid_diagnosis(dept_name: str, gender: str, age: int) -> dict:
    """
    Department-filtered diagnosis sampling that also avoids
    gender/age-impossible codes, mirroring repair_diagnoses' resample
    loop in validate_repair.py so generation rarely needs that repair.

    Some departments (e.g. OB/GYN) have a diagnosis pool that is almost
    entirely gender-restricted, so a bounded resample within that
    department can still fail for a mismatched patient. If it does,
    fall back to sampling the full (unfiltered-by-department) list,
    which always has plenty of gender/age-safe codes.
    """
    forbidden = set()
    if gender == 'M':
        forbidden |= MALE_IMPOSSIBLE_CODES
    elif gender == 'F':
        forbidden |= FEMALE_IMPOSSIBLE_CODES
    if age is None or age > 1:
        forbidden |= NEWBORN_ONLY_CODES

    dx = sample_diagnosis(dept_name)
    attempts = 0
    while dx['icd10_code'] in forbidden and attempts < 10:
        dx = sample_diagnosis(dept_name)
        attempts += 1

    if dx['icd10_code'] in forbidden:
        dx = sample_diagnosis()
        attempts = 0
        while dx['icd10_code'] in forbidden and attempts < 20:
            dx = sample_diagnosis()
            attempts += 1

    return dx


# =============================================================================
# GENERATORS
# =============================================================================

def gen_departments(conn) -> list:
    print("  Inserting departments...")
    sql = """INSERT INTO departments (department_id, dep_name, floor_number, bed_capacity)
             VALUES (:department_id, :dep_name, :floor_number, :bed_capacity)"""
    execute_batch(conn, sql, DEPARTMENTS_DATA)
    ids = [d["department_id"] for d in DEPARTMENTS_DATA]
    print(f"    {len(ids)} departments inserted")
    return ids


def gen_payers(conn) -> list:
    print("  Inserting payers...")
    sql = """INSERT INTO payers (payer_id, payer_name, payer_type, contact_phone)
             VALUES (:payer_id, :payer_name, :payer_type, :contact_phone)"""
    execute_batch(conn, sql, PAYERS_DATA)
    ids = [p["payer_id"] for p in PAYERS_DATA]
    print(f"    {len(ids)} payers inserted")
    return ids


def gen_procedures(conn) -> list:
    print("  Inserting procedures...")
    sql = """INSERT INTO procedures
             (procedure_id, procedure_code, procedure_name, department_id,
              base_cost, duration_minutes)
             VALUES (:procedure_id, :procedure_code, :procedure_name,
                     :department_id, :base_cost, :duration_minutes)"""
    execute_batch(conn, sql, PROCEDURES_DATA)
    ids = [p["procedure_id"] for p in PROCEDURES_DATA]
    print(f"    {len(ids)} procedures inserted")
    return ids


def gen_patients(conn, cfg: dict) -> list:
    print(f"  Generating {cfg['patients']} patients...")
    sql = """INSERT INTO patients
             (patient_id, first_name, last_name, ssn, birth_date, age,
              gender, blood_type, phone, email, address, city, state,
              zip_code, country, registered_date)
             VALUES (:patient_id, :first_name, :last_name, :ssn, :birth_date, :age,
                     :gender, :blood_type, :phone, :email, :address, :city, :state,
                     :zip_code, :country, :registered_date)"""

    blood_types = ['A+',   'A-',   'B+',   'B-',   'AB+',  'AB-',  'O+',   'O-']
    blood_probs = np.array([0.355, 0.060, 0.085, 0.020, 0.030, 0.010, 0.375, 0.065])
    blood_probs = blood_probs / blood_probs.sum()

    states = [
        'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN',
        'IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV',
        'NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN',
        'TX','UT','VT','VA','WA','WV','WI','WY'
    ]
    state_probs = np.array([0.01] * len(states), dtype=np.float64)
    state_probs[states.index('FL')] = 0.35
    state_probs = state_probs / state_probs.sum()

    reg_start   = date(2015, 1, 1)
    reg_end     = AS_OF.date()
    rows        = []
    patient_ids = []

    for _ in range(cfg['patients']):
        pid     = gen_id("PAT")
        gender  = np.random.choice(['M', 'F', 'NB'], p=[0.48, 0.48, 0.04])
        dob     = sample_birth_date()
        age     = age_from_dob(dob)
        country = np.random.choice(['USA', fake.country_code()], p=[0.97, 0.03])
        state   = np.random.choice(states, p=state_probs) if country == 'USA' else 'N/A'

        rows.append({
            "patient_id":      pid,
            "first_name":      gender_name(gender),
            "last_name":       fake.last_name(),
            "ssn":             fake.ssn(),
            "birth_date":      dob,
            "age":             age,
            "gender":          gender,
            "blood_type":      np.random.choice(blood_types, p=blood_probs),
            "phone":           fake.phone_number()[:20],
            "email":           fake.email() if age >= 13 else None,
            "address":         fake.street_address(),
            "city":            fake.city(),
            "state":           state,
            "zip_code":        fake.postcode()[:10],
            "country":         country,
            "registered_date": random_date_between(max(reg_start, dob), reg_end),
        })
        patient_ids.append(pid)

    execute_batch(conn, sql, rows)
    print(f"    {len(patient_ids)} patients inserted")
    return patient_ids


def gen_doctors(conn, cfg: dict, dept_ids: list) -> list:
    print(f"  Generating {cfg['doctors']} doctors...")
    sql = """INSERT INTO doctors
             (doctor_id, first_name, last_name, birth_date, gender,
              contact, specialty, department_id, hire_date)
             VALUES (:doctor_id, :first_name, :last_name, :birth_date, :gender,
                     :contact, :specialty, :department_id, :hire_date)"""

    rows       = []
    doctor_ids = []
    hire_start = date(2000, 1, 1)
    window_open = date(2019, 12, 31)       # admissions start 2020-01-01

    def make_doctor(specialty, dept_id, early=False):
        gender = np.random.choice(['M', 'F', 'NB'], p=[0.55, 0.42, 0.03])
        birth  = fake.date_of_birth(minimum_age=45 if early else 28, maximum_age=70)
        return {
            "doctor_id":     gen_id("DOC"),
            "first_name":    gender_name(gender),
            "last_name":     fake.last_name(),
            "birth_date":    birth,
            "gender":        gender,
            "contact":       fake.phone_number()[:20],
            "specialty":     specialty,
            "department_id": dept_id,
            "hire_date":     hire_date_for(birth, hire_start, 25, window_open if early else None),
        }

    for _ in range(cfg['doctors']):
        specialty = random.choice(DOCTOR_SPECIALTIES)
        dept_id   = random.choice(SPECIALTY_TO_DEPARTMENT.get(specialty, dept_ids))
        rows.append(make_doctor(specialty, dept_id))

    # Guarantee at least one doctor per department (mirrors gen_rooms'
    # guarantee) — otherwise departments with no doctors produce
    # doctor_dept_mismatch violations that repair_department can never
    # fix, since it has no doctor in that department to reassign to.
    assigned_depts = {r["department_id"] for r in rows}
    dept_to_specialties = defaultdict(list)
    for specialty, depts in SPECIALTY_TO_DEPARTMENT.items():
        for d in depts:
            dept_to_specialties[d].append(specialty)

    for dept_id in [d for d in dept_ids if d not in assigned_depts]:
        specialty = random.choice(dept_to_specialties.get(dept_id) or DOCTOR_SPECIALTIES)
        rows.append(make_doctor(specialty, dept_id, early=True))
        print(f"    Guaranteed doctor added for {dept_id}")

    # ...and make sure every department has someone hired before the data
    # window opens, so early admissions can always be assigned a doctor who
    # had actually started work by then.
    for dept_id in dept_ids:
        members = [r for r in rows if r["department_id"] == dept_id]
        if members and not any(r["hire_date"] <= window_open for r in members):
            old = make_doctor(members[0]["specialty"], dept_id, early=True)
            members[0].update(birth_date=old["birth_date"], hire_date=old["hire_date"])

    doctor_ids = [r["doctor_id"] for r in rows]
    execute_batch(conn, sql, rows)
    print(f"    {len(doctor_ids)} doctors inserted")
    return doctor_ids


def gen_nurses(conn, cfg: dict, dept_ids: list) -> list:
    print(f"  Generating {cfg['nurses']} nurses...")
    sql = """INSERT INTO nurses
             (nurse_id, first_name, last_name, birth_date, gender,
              contact, position, department_id, hire_date)
             VALUES (:nurse_id, :first_name, :last_name, :birth_date, :gender,
                     :contact, :position, :department_id, :hire_date)"""

    rows       = []
    nurse_ids  = []
    hire_start = date(2000, 1, 1)

    for _ in range(cfg['nurses']):
        nid          = gen_id("NUR")
        gender       = np.random.choice(['M', 'F', 'NB'], p=[0.11, 0.83, 0.06])
        position     = random.choice(NURSE_POSITIONS)
        dept_options = NURSE_POSITION_TO_DEPARTMENT.get(position)
        dept_id      = random.choice(dept_options if dept_options else dept_ids)
        birth        = fake.date_of_birth(minimum_age=22, maximum_age=65)

        rows.append({
            "nurse_id":      nid,
            "first_name":    gender_name(gender),
            "last_name":     fake.last_name(),
            "birth_date":    birth,
            "gender":        gender,
            "contact":       fake.phone_number()[:20],
            "position":      position,
            "department_id": dept_id,
            "hire_date":     hire_date_for(birth, hire_start, 21),
        })
        nurse_ids.append(nid)

    execute_batch(conn, sql, rows)
    print(f"    {len(nurse_ids)} nurses inserted")
    return nurse_ids


def gen_employees(conn, cfg: dict, dept_ids: list) -> list:
    print(f"  Generating {cfg['employees']} employees...")
    sql = """INSERT INTO employees
             (employee_id, first_name, last_name, gender, position,
              department_id, contact, salary, hire_date)
             VALUES (:employee_id, :first_name, :last_name, :gender, :position,
                     :department_id, :contact, :salary, :hire_date)"""

    salary_ranges = {
        'Hospital Administrator':       (90000,  180000),
        'Health Information Manager':   (65000,  100000),
        'Billing Specialist':           (38000,   58000),
        'Medical Coder':                (42000,   65000),
        'IT Analyst':                   (55000,   90000),
        'Facilities Manager':           (50000,   80000),
        'HR Coordinator':               (45000,   70000),
        'Patient Services Coordinator': (35000,   52000),
        'Medical Receptionist':         (30000,   46000),
        'Supply Chain Coordinator':     (45000,   70000),
        'Quality Assurance Analyst':    (55000,   85000),
        'Compliance Officer':           (70000,  110000),
    }

    rows         = []
    employee_ids = []
    hire_start   = date(2005, 1, 1)

    for _ in range(cfg['employees']):
        eid      = gen_id("EMP")
        gender   = np.random.choice(['M', 'F', 'NB'], p=[0.45, 0.50, 0.05])
        position = random.choice(EMPLOYEE_POSITIONS)
        dept_id  = random.choice(dept_ids) if random.random() > 0.3 else None
        sal_min, sal_max = salary_ranges.get(position, (35000, 75000))

        rows.append({
            "employee_id":   eid,
            "first_name":    gender_name(gender),
            "last_name":     fake.last_name(),
            "gender":        gender,
            "position":      position,
            "department_id": dept_id,
            "contact":       fake.phone_number()[:20],
            "salary":        round(random.uniform(sal_min, sal_max), 2),
            "hire_date":     random_date_between(hire_start, AS_OF.date()),
        })
        employee_ids.append(eid)

    execute_batch(conn, sql, rows)
    print(f"    {len(employee_ids)} employees inserted")
    return employee_ids


def gen_rooms(conn, cfg: dict, dept_ids: list) -> list:
    print(f"  Generating {cfg['rooms']} rooms...")
    sql = """INSERT INTO rooms
             (room_id, room_number, room_type, floor_number, bed_capacity,
              department_id, status)
             VALUES (:room_id, :room_number, :room_type, :floor_number, :bed_capacity,
                     :department_id, :status)"""

    bed_capacity_map = {
        'Standard': 2, 'Private': 1, 'ICU': 1, 'NICU': 1,
        'OR': 1, 'ER': 2, 'Recovery': 2, 'Isolation': 1
    }

    rows         = []
    room_ids     = []
    room_numbers = random.sample(range(100, 999), min(cfg['rooms'], 899))

    for i in range(cfg['rooms']):
        rid       = gen_id("RMN")
        room_type = np.random.choice(ROOM_TYPES, p=ROOM_TYPE_P)
        dept_id   = random.choice(dept_ids)
        dept_obj  = next((d for d in DEPARTMENTS_DATA if d["department_id"] == dept_id), None)
        floor_num = dept_obj["floor_number"] if dept_obj else random.randint(1, 6)

        rows.append({
            "room_id":       rid,
            "room_number":   str(room_numbers[i]),
            "room_type":     room_type,
            "floor_number":  floor_num,
            "bed_capacity":  bed_capacity_map.get(room_type, 1),
            "department_id": dept_id,
            "status":        np.random.choice(
                                 ['Available', 'Occupied', 'Maintenance'],
                                 p=[0.50, 0.42, 0.08]
                             ),
        })
        room_ids.append(rid)

    # ── Guarantee at least one room per department ────────────────────────
    assigned_depts = {r["department_id"] for r in rows}
    missing_depts  = [d for d in dept_ids if d not in assigned_depts]

    for dept_id in missing_depts:
        dept_obj  = next((d for d in DEPARTMENTS_DATA if d["department_id"] == dept_id), None)
        floor_num = dept_obj["floor_number"] if dept_obj else 1
        rid       = gen_id("RMN")
        rows.append({
            "room_id":       rid,
            "room_number":   str(random.randint(100, 999)),
            "room_type":     "Standard",
            "floor_number":  floor_num,
            "bed_capacity":  2,
            "department_id": dept_id,
            "status":        "Available",
        })
        room_ids.append(rid)
        print(f"    Guaranteed room added for {dept_id}")

    execute_batch(conn, sql, rows)
    print(f"    {len(room_ids)} rooms inserted")
    return room_ids


def _load_patient_info(conn) -> dict:
    """{patient_id: (age, birth_date)} — drives age-aware, birth-aware admissions."""
    result = conn.execute(text("SELECT patient_id, age, birth_date FROM patients"))
    return {row[0]: (row[1], row[2]) for row in result}


def _load_staff_pool(conn, table: str, id_col: str) -> StaffPool:
    result = conn.execute(text(f"SELECT {id_col}, hire_date, department_id FROM {table} ORDER BY {id_col}"))
    return StaffPool([(r[0], r[1], r[2]) for r in result])


def gen_admissions(conn, cfg: dict, patient_ids: list, dept_ids: list,
                   patient_info: dict, doctor_pool: StaffPool) -> list:
    print(f"  Generating {cfg['admissions']} admissions...")
    sql = """INSERT INTO admissions
             (admission_id, patient_id, admitting_doctor_id, department_id,
              room_id, admission_date, discharge_date, admission_type,
              admission_status, discharge_disposition, patient_condition,
              length_of_stay)
             VALUES (:admission_id, :patient_id, :admitting_doctor_id, :department_id,
                     :room_id, :admission_date, :discharge_date, :admission_type,
                     :admission_status, :discharge_disposition, :patient_condition,
                     :length_of_stay)"""

    # Build dept -> room and dept -> room_type -> room lookups
    result = conn.execute(text("SELECT room_id, department_id, room_type FROM rooms ORDER BY room_id"))
    dept_room_map      = defaultdict(list)
    dept_room_type_map = defaultdict(lambda: defaultdict(list))
    for row in result:
        dept_room_map[row[1]].append(row[0])
        dept_room_type_map[row[1]][row[2]].append(row[0])

    # Adult pool excludes Pediatrics so adults never land in DEP-008
    adult_dept_pool = [d for d in dept_ids if d != 'DEP-008']

    adm_start    = datetime(2020, 1, 1)
    now          = AS_OF
    latest_past  = now - timedelta(minutes=5)
    newborn_done = set()
    rows         = []
    adm_ids      = []

    for _ in range(cfg['admissions']):
        aid          = gen_id("ADM")
        patient_id   = random.choice(patient_ids)
        age, dob     = patient_info[patient_id]
        category     = np.random.choice(ADMISSION_CATEGORIES, p=ADMISSION_CATEGORY_P)

        # Department driven by patient age
        if age == 0:
            dept_id = random.choice(NEWBORN_DEPT_POOL)
        elif age <= 17:
            dept_id = random.choice(PEDIATRIC_DEPT_POOL)
        else:
            dept_id = random.choice(adult_dept_pool)

        # Admission type: Newborn only for a newborn's first completed admission
        if category == 'Scheduled':
            adm_type = np.random.choice(SCHEDULED_TYPES, p=SCHEDULED_TYPE_P)
        elif age == 0 and category == 'Completed':
            if patient_id in newborn_done:
                adm_type = np.random.choice(NEWBORN_REPEAT_TYPES, p=NEWBORN_REPEAT_TYPE_P)
            else:
                adm_type = np.random.choice(NEWBORN_ADM_TYPES, p=NEWBORN_ADM_TYPE_P)
        else:
            adm_type = np.random.choice(NON_NEWBORN_TYPES, p=NON_NEWBORN_TYPE_P)
        if adm_type == 'Newborn':
            newborn_done.add(patient_id)

        # Admission date: scheduled ones are in the future; everything else is
        # in the past and never before the patient was born (newborns are
        # admitted at birth).
        if category == 'Scheduled':
            adm_dt = random_datetime_between(now + timedelta(days=1), now + timedelta(days=90))
        elif adm_type == 'Newborn':
            adm_dt = datetime.combine(dob, dtime(8, 0)) + timedelta(hours=random.randint(0, 40))
        else:
            adm_dt = random_datetime_between(
                max(adm_start, datetime.combine(dob, dtime(0, 0))), latest_past
            )

        # Doctor matched to the admission department AND already hired
        doc_id, adm_dt = doctor_pool.pick_with_date(adm_dt, dept_id)
        if category != 'Scheduled' and adm_dt > latest_past:
            adm_dt = latest_past

        condition = np.random.choice(
                        ['Minimal', 'Moderate', 'Maximum', 'Intensive'],
                        p=[0.15, 0.40, 0.30, 0.15]
                    )

        # Status follows from the dates
        los, dis_dt, dis_dsp = None, None, 'Still Admitted'
        if category == 'Scheduled':
            status = 'Scheduled'
        elif category == 'Cancelled':
            status = 'Cancelled'
        else:
            los    = min(max(1, int(np.random.exponential(scale=5))), MAX_STAY_DAYS)
            dis_dt = adm_dt + timedelta(days=los)
            if dis_dt > now:                   # stay hasn't ended yet
                status, los, dis_dt = 'Admitted', None, None
            else:
                status  = 'Discharged'
                dis_dsp = np.random.choice(
                              DISCHARGE_DISPOSITIONS['options'],
                              p=DISCHARGE_DISPOSITIONS['probs']
                          )

        # Room matched to admission department AND patient_condition
        dept_rooms = dept_room_map.get(dept_id, [])
        room_id    = None
        if status in ['Admitted', 'Discharged'] and dept_rooms:
            allowed_types = CONDITION_ROOM_MAP.get(condition, [])
            candidates = [
                rid for rt in allowed_types
                for rid in dept_room_type_map.get(dept_id, {}).get(rt, [])
            ]
            room_id = random.choice(candidates) if candidates else random.choice(dept_rooms)

        rows.append({
            "admission_id":          aid,
            "patient_id":            patient_id,
            "admitting_doctor_id":   doc_id,
            "department_id":         dept_id,
            "room_id":               room_id,
            "admission_date":        adm_dt,
            "discharge_date":        dis_dt,
            "admission_type":        adm_type,
            "admission_status":      status,
            "discharge_disposition": dis_dsp,
            "patient_condition":     condition,
            "length_of_stay":        los,
        })
        adm_ids.append(aid)

    execute_batch(conn, sql, rows)
    print(f"    {len(adm_ids)} admissions inserted")
    return adm_ids


def _load_admission_windows(conn) -> tuple:
    """Return (adm_dt_map, dis_dt_map) dicts keyed by admission_id."""
    result     = conn.execute(text(
        "SELECT admission_id, admission_date, discharge_date FROM admissions"
    ))
    adm_dt_map = {}
    dis_dt_map = {}
    for row in result:
        adm_dt_map[row[0]] = row[1]
        if row[2]:
            dis_dt_map[row[0]] = row[2]
    return adm_dt_map, dis_dt_map


def _load_admission_clinical_info(conn) -> dict:
    """
    {admission_id: {dept_name, gender, age, status, admission_type}} — used to
    sample department-appropriate, gender/age-valid ICD-10 codes, age-banded
    vitals, and to decide which admissions get clinical records at all.
    """
    result = conn.execute(text("""
        SELECT a.admission_id, dpt.dep_name, p.gender, p.age,
               a.admission_status, a.admission_type
        FROM admissions a
        JOIN departments dpt ON a.department_id = dpt.department_id
        JOIN patients p      ON a.patient_id    = p.patient_id
    """))
    info_map = {}
    for row in result:
        info_map[row[0]] = {"dept_name": row[1], "gender": row[2], "age": row[3],
                            "status": row[4], "admission_type": row[5]}
    return info_map


def gen_triage(conn, clinical_ids: list, nurse_pool: StaffPool, adm_info_map: dict,
               adm_dt_map: dict, dis_dt_map: dict):
    target = [a for a in clinical_ids if random.random() < 0.80]
    print(f"  Generating triage for {len(target)} admissions...")
    sql = """INSERT INTO triage
             (triage_id, admission_id, nurse_id, triage_datetime,
              bp_systolic, bp_diastolic, heart_rate, temperature,
              respiratory_rate, oxygen_saturation, height_cm, weight_kg,
              pain_level, chief_complaint, acuity_level)
             VALUES (:triage_id, :admission_id, :nurse_id, :triage_datetime,
                     :bp_systolic, :bp_diastolic, :heart_rate, :temperature,
                     :respiratory_rate, :oxygen_saturation, :height_cm, :weight_kg,
                     :pain_level, :chief_complaint, :acuity_level)"""

    acuity_p = [0.05, 0.20, 0.40, 0.25, 0.10]
    rows = []
    for adm_id in target:
        adm_dt    = adm_dt_map[adm_id]
        dis_dt    = dis_dt_map.get(adm_id)
        info      = adm_info_map[adm_id]
        v         = _vitals_for_age(info['age'])
        triage_dt = datetime_within_admission(adm_dt, dis_dt)

        if info['admission_type'] == 'Emergency':      # ESI 1-3 only
            acuity = np.random.choice([1, 2, 3], p=[p / sum(acuity_p[:3]) for p in acuity_p[:3]])
        else:
            acuity = np.random.choice([1, 2, 3, 4, 5], p=acuity_p)

        rows.append({
            "triage_id":         gen_id("TRI"),
            "admission_id":      adm_id,
            "nurse_id":          nurse_pool.pick(triage_dt),
            "triage_datetime":   triage_dt,
            "bp_systolic":       random.randint(*v['sbp']),
            "bp_diastolic":      random.randint(*v['dbp']),
            "heart_rate":        random.randint(*v['hr']),
            "temperature":       round(random.uniform(97.0, 103.5), 1),
            "respiratory_rate":  random.randint(*v['rr']),
            "oxygen_saturation": random.randint(88, 100),
            "height_cm":         random.randint(*v['h']),
            "weight_kg":         round(random.uniform(*v['w']), 1),
            "pain_level":        random.randint(0, 10),
            "chief_complaint":   random.choice(CHIEF_COMPLAINTS),
            "acuity_level":      acuity,
        })

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} triage records inserted")


def gen_diagnoses(conn, cfg: dict, admission_ids: list, doctor_pool: StaffPool,
                  adm_dt_map: dict, dis_dt_map: dict, adm_info_map: dict):
    print(f"  Generating diagnoses...")
    sql = """INSERT INTO diagnoses
             (diagnosis_id, admission_id, doctor_id, icd10_code,
              diagnosis_date, diagnosis_type)
             VALUES (:diagnosis_id, :admission_id, :doctor_id, :icd10_code,
                     :diagnosis_date, :diagnosis_type)"""

    rows = []
    for adm_id in admission_ids:
        adm_dt = adm_dt_map.get(adm_id, AS_OF)
        dis_dt = dis_dt_map.get(adm_id)
        count  = max(1, poisson_count(cfg['avg_diagnoses']))

        info       = adm_info_map.get(adm_id, {})
        dept_name  = info.get('dept_name')
        gender     = info.get('gender')
        age        = info.get('age')

        for i in range(count):
            dx      = _sample_valid_diagnosis(dept_name, gender, age)
            dx_type = 'Primary' if i == 0 else np.random.choice(
                          ['Secondary', 'Tertiary', 'Complication'],
                          p=[0.50, 0.25, 0.25]
                      )
            dx_date = date_within_admission(adm_dt, dis_dt)
            rows.append({
                "diagnosis_id":   gen_id("DXX"),
                "admission_id":   adm_id,
                "doctor_id":      doctor_pool.pick(dx_date),
                "icd10_code":     dx['icd10_code'],
                "diagnosis_date": dx_date,
                "diagnosis_type": dx_type,
            })

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} diagnoses inserted")


def gen_patient_procedures(conn, cfg: dict, admission_ids: list,
                           doctor_pool: StaffPool, adm_dt_map: dict,
                           dis_dt_map: dict) -> list:
    print(f"  Generating patient procedures...")
    sql = """INSERT INTO patient_procedures
             (patient_procedure_id, admission_id, procedure_id, doctor_id,
              procedure_date, procedure_status, notes)
             VALUES (:patient_procedure_id, :admission_id, :procedure_id, :doctor_id,
                     :procedure_date, :procedure_status, :notes)"""

    proc_ids    = [p["procedure_id"] for p in PROCEDURES_DATA]
    pp_statuses = ['Completed', 'Scheduled', 'Cancelled']
    pp_status_p = [0.75, 0.18, 0.07]
    rows        = []
    pp_ids      = []

    for adm_id in admission_ids:
        adm_dt = adm_dt_map.get(adm_id, AS_OF)
        dis_dt = dis_dt_map.get(adm_id)
        count  = poisson_count(cfg['avg_procedures'])

        for _ in range(count):
            ppid    = gen_id("PRP")
            pp_date = datetime_within_admission(adm_dt, dis_dt)
            rows.append({
                "patient_procedure_id": ppid,
                "admission_id":         adm_id,
                "procedure_id":         random.choice(proc_ids),
                "doctor_id":            doctor_pool.pick(pp_date),
                "procedure_date":       pp_date,
                "procedure_status":     np.random.choice(pp_statuses, p=pp_status_p),
                "notes":                None,
            })
            pp_ids.append(ppid)

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} patient procedures inserted")
    return pp_ids


def gen_medications(conn, cfg: dict, admission_ids: list, doctor_pool: StaffPool,
                    adm_dt_map: dict, dis_dt_map: dict):
    print(f"  Generating medications...")
    sql = """INSERT INTO medications
             (medication_id, admission_id, doctor_id, drug_name, dosage,
              frequency, start_date, end_date, med_status)
             VALUES (:medication_id, :admission_id, :doctor_id, :drug_name, :dosage,
                     :frequency, :start_date, :end_date, :med_status)"""

    med_statuses = ['Active', 'Discontinued', 'Completed']
    med_status_p = [0.30, 0.20, 0.50]
    rows         = []

    for adm_id in admission_ids:
        adm_dt = adm_dt_map.get(adm_id, AS_OF)
        dis_dt = dis_dt_map.get(adm_id)
        count  = poisson_count(cfg['avg_medications'])

        for _ in range(count):
            med        = random.choice(MEDICATIONS_LIST)
            start      = date_within_admission(adm_dt, dis_dt)
            med_status = np.random.choice(med_statuses, p=med_status_p)
            end_dt     = None
            if med_status in ['Discontinued', 'Completed']:
                window_end = dis_dt.date() if dis_dt else AS_OF.date()
                end_dt     = random_date_between(start, window_end)

            rows.append({
                "medication_id": gen_id("MED"),
                "admission_id":  adm_id,
                "doctor_id":     doctor_pool.pick(start),
                "drug_name":     med["drug_name"],
                "dosage":        med["dosage"],
                "frequency":     med["frequency"],
                "start_date":    start,
                "end_date":      end_dt,
                "med_status":    med_status,
            })

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} medications inserted")


def gen_medical_tests(conn, cfg: dict, admission_ids: list,
                      doctor_pool: StaffPool, nurse_pool: StaffPool,
                      adm_dt_map: dict, dis_dt_map: dict) -> list:
    print(f"  Generating medical tests...")
    sql = """INSERT INTO medical_tests
             (test_id, admission_id, doctor_id, nurse_id, test_name,
              test_category, test_date, result, result_date, cost)
             VALUES (:test_id, :admission_id, :doctor_id, :nurse_id, :test_name,
                     :test_category, :test_date, :result, :result_date, :cost)"""

    test_catalog = {
        'Blood Panel':  [('Complete Blood Count', 120), ('Basic Metabolic Panel', 95),
                         ('Comprehensive Metabolic Panel', 145), ('Lipid Panel', 85),
                         ('Thyroid Panel', 130), ('Coagulation Panel', 160)],
        'Urinalysis':   [('Urinalysis with Microscopy', 65), ('Urine Culture', 80)],
        'Imaging':      [('Chest X-Ray', 220), ('CT Abdomen', 1800), ('MRI Brain', 2400),
                         ('Ultrasound Abdomen', 650), ('Echocardiogram', 1500)],
        'Pathology':    [('Tissue Biopsy', 350), ('Pap Smear', 90), ('Bone Marrow Biopsy', 800)],
        'Cardiology':   [('12-Lead EKG', 180), ('Stress Test', 900), ('Holter Monitor', 450)],
        'Microbiology': [('Blood Culture', 140), ('Wound Culture', 110), ('Sputum Culture', 95)],
        'Neurology':    [('EEG', 900), ('Nerve Conduction Study', 650), ('Lumbar Puncture', 1100)],
    }

    categories  = list(test_catalog.keys())
    result_opts = ['Normal', 'Abnormal - Mild', 'Abnormal - Moderate',
                   'Abnormal - Severe', 'Inconclusive', 'Pending']
    result_p    = [0.45, 0.25, 0.15, 0.05, 0.05, 0.05]
    rows        = []
    test_ids    = []

    for adm_id in admission_ids:
        adm_dt = adm_dt_map.get(adm_id, AS_OF)
        dis_dt = dis_dt_map.get(adm_id)
        count  = poisson_count(cfg['avg_tests'])

        for _ in range(count):
            tid           = gen_id("TST")
            category      = random.choice(categories)
            test_nm, cost = random.choice(test_catalog[category])
            test_dt       = datetime_within_admission(adm_dt, dis_dt)
            result        = np.random.choice(result_opts, p=result_p)

            if result != 'Pending':
                max_res  = dis_dt.date() if dis_dt else AS_OF.date()
                res_date = random_date_between(
                    test_dt.date(), max(test_dt.date(), max_res)
                )
            else:
                res_date = None

            rows.append({
                "test_id":       tid,
                "admission_id":  adm_id,
                "doctor_id":     doctor_pool.pick(test_dt),
                "nurse_id":      nurse_pool.pick(test_dt) if random.random() > 0.3 else None,
                "test_name":     test_nm,
                "test_category": category,
                "test_date":     test_dt,
                "result":        result if result != 'Pending' else None,
                "result_date":   res_date,
                "cost":          round(cost * random.uniform(0.85, 1.15), 2),
            })
            test_ids.append(tid)

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} medical tests inserted")
    return test_ids


def gen_staff_shifts(conn, cfg: dict, dept_ids: list):
    print(f"  Generating staff shifts...")
    sql = """INSERT INTO staff_shifts
             (shift_id, staff_id, staff_type, department_id,
              shift_date, shift_type, hours_worked)
             VALUES (:shift_id, :staff_id, :staff_type, :department_id,
                     :shift_date, :shift_type, :hours_worked)"""

    shift_start = date(2023, 1, 1)
    shift_end   = AS_OF.date()
    n           = cfg['shifts_per_staff']
    rows        = []

    staff = []
    for table, id_col, staff_type in [('doctors', 'doctor_id', 'Doctor'),
                                      ('nurses', 'nurse_id', 'Nurse'),
                                      ('employees', 'employee_id', 'Employee')]:
        result = conn.execute(text(f"SELECT {id_col}, department_id, hire_date FROM {table} ORDER BY {id_col}"))
        staff += [(r[0], staff_type, r[1], r[2]) for r in result]

    for staff_id, staff_type, home_dept, hire_date in staff:
        for _ in range(n):
            rows.append({
                "shift_id":      gen_id("SHF"),
                "staff_id":      staff_id,
                "staff_type":    staff_type,
                "department_id": home_dept or random.choice(dept_ids),
                "shift_date":    random_date_between(max(shift_start, hire_date), shift_end),
                "shift_type":    random.choice(SHIFT_TYPES),
                "hours_worked":  random.choice([8.0, 10.0, 12.0]),
            })

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} staff shifts inserted")


def gen_billing(conn):
    """
    One bill per discharged admission, built bottom-up from that admission's own
    room stay, completed procedures, tests, medications and a consultation —
    so line items always belong to the bill's admission and the bill total is
    the sum of its line items (no reconciliation needed afterwards).
    """
    print(f"  Generating billing records...")
    bill_sql = """INSERT INTO billing
             (bill_id, admission_id, patient_id, payer_id, bill_date,
              due_date, total_amount, insurance_covered, patient_responsibility,
              payment_status, payment_date)
             VALUES (:bill_id, :admission_id, :patient_id, :payer_id, :bill_date,
                     :due_date, :total_amount, :insurance_covered,
                     :patient_responsibility, :payment_status, :payment_date)"""
    item_sql = """INSERT INTO billing_line_items
             (line_item_id, bill_id, item_type, patient_procedure_id,
              test_id, description, quantity, unit_cost, total_cost, covered_amount)
             VALUES (:line_item_id, :bill_id, :item_type, :patient_procedure_id,
                     :test_id, :description, :quantity, :unit_cost,
                     :total_cost, :covered_amount)"""

    procs, tests, meds = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in conn.execute(text("""
            SELECT pp.admission_id, pp.patient_procedure_id, pr.procedure_name, pr.base_cost
            FROM patient_procedures pp JOIN procedures pr ON pr.procedure_id = pp.procedure_id
            WHERE pp.procedure_status = 'Completed' ORDER BY pp.patient_procedure_id""")):
        procs[r[0]].append(r[1:])
    for r in conn.execute(text("SELECT admission_id, test_id, test_name, cost FROM medical_tests ORDER BY test_id")):
        tests[r[0]].append(r[1:])
    for r in conn.execute(text("SELECT admission_id, drug_name, dosage FROM medications ORDER BY medication_id")):
        meds[r[0]].append(r[1:])

    admissions = conn.execute(text("""
        SELECT a.admission_id, a.patient_id, a.length_of_stay, a.discharge_date, r.room_type
        FROM admissions a LEFT JOIN rooms r ON r.room_id = a.room_id
        WHERE a.admission_status = 'Discharged' ORDER BY a.admission_id""")).fetchall()

    consult_desc = ['Specialist Consultation', 'Initial Consultation',
                    'Follow-up Consultation', 'Telemedicine Consultation']
    pmt_statuses = ['Pending', 'Partial', 'Paid', 'Denied', 'Write-Off']
    pmt_status_p = [0.20, 0.15, 0.50, 0.10, 0.05]
    today        = AS_OF.date()
    bill_rows, item_rows = [], []

    for adm_id, pat_id, los, dis_dt, room_type in admissions:
        bid        = gen_id("BIL")
        payer      = random.choice(PAYERS_DATA)
        coverage   = PAYER_COVERAGE[payer["payer_type"]]
        pmt_status = np.random.choice(pmt_statuses, p=pmt_status_p)
        cover_f    = 0.0 if pmt_status == 'Denied' else coverage

        # (item_type, procedure_id, test_id, description, qty, unit_cost)
        items = []
        lo, hi, room_desc = ROOM_RATES.get(room_type, ROOM_RATES['Standard'])
        items.append(('Room', None, None, room_desc,
                      1 if room_type == 'ER' else max(1, los or 1), round(random.uniform(lo, hi), 2)))
        for pp_id, name, base_cost in procs.get(adm_id, []):
            items.append(('Procedure', pp_id, None, name, 1,
                          round(float(base_cost) * random.uniform(0.9, 1.1), 2)))
        for t_id, name, cost in tests.get(adm_id, []):
            items.append(('Lab', None, t_id, name, 1, float(cost)))
        for drug, dosage in meds.get(adm_id, []):
            items.append(('Medication', None, None, f"{drug} {dosage}",
                          random.randint(1, max(2, min(30, (los or 1) * 3))),
                          round(random.uniform(5, 250), 2)))
        if random.random() < 0.7:
            items.append(('Consultation', None, None, random.choice(consult_desc), 1,
                          round(random.uniform(200, 800), 2)))

        total = 0.0
        for item_type, pp_id, t_id, desc, qty, unit_cost in items:
            total_cost = round(unit_cost * qty, 2)
            total     += total_cost
            item_rows.append({
                "line_item_id":         gen_id("LIN"),
                "bill_id":              bid,
                "item_type":            item_type,
                "patient_procedure_id": pp_id,
                "test_id":              t_id,
                "description":          desc,
                "quantity":             qty,
                "unit_cost":            unit_cost,
                "total_cost":           total_cost,
                "covered_amount":       round(total_cost * cover_f, 2),
            })
        total   = round(total, 2)
        ins_cov = round(total * cover_f, 2)
        pat_res = 0.0 if pmt_status == 'Write-Off' else round(total - ins_cov, 2)

        # billed 0-90 days after discharge, never in the future
        start    = dis_dt.date() if isinstance(dis_dt, datetime) else dis_dt
        bill_dt  = random_date_between(start, max(start, min(start + timedelta(days=90), today)))
        pmt_date = min(bill_dt + timedelta(days=random.randint(5, 90)), today) \
                   if pmt_status == 'Paid' else None

        bill_rows.append({
            "bill_id":                bid,
            "admission_id":           adm_id,
            "patient_id":             pat_id,
            "payer_id":               payer["payer_id"],
            "bill_date":              bill_dt,
            "due_date":               bill_dt + timedelta(days=30),
            "total_amount":           total,
            "insurance_covered":      ins_cov,
            "patient_responsibility": pat_res,
            "payment_status":         pmt_status,
            "payment_date":           pmt_date,
        })

    execute_batch(conn, bill_sql, bill_rows)
    print(f"    {len(bill_rows)} billing records inserted")
    execute_batch(conn, item_sql, item_rows)
    print(f"    {len(item_rows)} billing line items inserted")





# =============================================================================
# TRUNCATE HELPER
# =============================================================================

def truncate_all(engine):
    """Wipe all tables cleanly before a fresh generation run."""
    tables = [
        'billing_line_items', 'billing', 'staff_shifts', 'medical_tests',
        'medications', 'patient_procedures', 'diagnoses', 'triage',
        'admissions', 'rooms', 'employees', 'nurses', 'doctors',
        'patients', 'procedures', 'payers', 'departments'
    ]
    with engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in tables:
            conn.execute(text(f"TRUNCATE TABLE {table}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        conn.commit()
    print("  All tables truncated.\n")


# =============================================================================
# MAIN
# =============================================================================

def main(size: str = "medium"):
    if size not in HOSPITAL_SIZES:
        print(f"Invalid size '{size}'. Choose from: small, medium, large")
        return

    cfg = HOSPITAL_SIZES[size]
    print(f"\n{'='*60}")
    print(f"  Hospital Database Generator (constraint-aware)")
    print(f"  Config: {size.upper()} — {cfg['description']}")
    print(f"{'='*60}\n")

    engine = create_engine(DB_URL, echo=False)
    truncate_all(engine)

    with engine.connect() as conn:

        # ── Domain 1: Reference tables ──────────────────────────────────────
        print("[ Domain 1 ] Reference tables")
        dept_ids  = gen_departments(conn)
        payer_ids = gen_payers(conn)
        proc_ids  = gen_procedures(conn)
        conn.commit()

        # ── Domain 2: Staff & Facilities ────────────────────────────────────
        print("\n[ Domain 2 ] Staff & Facilities")
        patient_ids  = gen_patients(conn, cfg)
        doctor_ids   = gen_doctors(conn, cfg, dept_ids)
        nurse_ids    = gen_nurses(conn, cfg, dept_ids)
        employee_ids = gen_employees(conn, cfg, dept_ids)
        room_ids     = gen_rooms(conn, cfg, dept_ids)
        conn.commit()

        patient_info = _load_patient_info(conn)
        doctor_pool  = _load_staff_pool(conn, 'doctors', 'doctor_id')
        nurse_pool   = _load_staff_pool(conn, 'nurses', 'nurse_id')

        # ── Domain 3: Clinical ──────────────────────────────────────────────
        print("\n[ Domain 3 ] Clinical")
        admission_ids = gen_admissions(
            conn, cfg, patient_ids, dept_ids, patient_info, doctor_pool
        )

        adm_dt_map, dis_dt_map = _load_admission_windows(conn)
        adm_info_map = _load_admission_clinical_info(conn)

        # Only admissions that actually happened (in progress or finished)
        # get clinical records; scheduled and cancelled ones don't.
        clinical_ids = [a for a in admission_ids
                        if adm_info_map[a]['status'] in ('Admitted', 'Discharged')]

        gen_triage(conn, clinical_ids, nurse_pool, adm_info_map, adm_dt_map, dis_dt_map)
        gen_diagnoses(
            conn, cfg, clinical_ids, doctor_pool, adm_dt_map, dis_dt_map, adm_info_map
        )
        gen_patient_procedures(
            conn, cfg, clinical_ids, doctor_pool, adm_dt_map, dis_dt_map
        )
        gen_medications(conn, cfg, clinical_ids, doctor_pool, adm_dt_map, dis_dt_map)
        gen_medical_tests(
            conn, cfg, clinical_ids, doctor_pool, nurse_pool, adm_dt_map, dis_dt_map
        )
        gen_staff_shifts(conn, cfg, dept_ids)
        conn.commit()

        # ── Domain 4: Financial ─────────────────────────────────────────────
        print("\n[ Domain 4 ] Financial")
        gen_billing(conn)
        conn.commit()

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  Generation complete. Row counts:")
    print(f"{'='*60}")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM vw_table_summary"))
        for row in result:
            print(f"  {row[0]:<30} {row[1]:>8,} rows")
    print(f"\n  hospital_db is ready for analysis.\n")
