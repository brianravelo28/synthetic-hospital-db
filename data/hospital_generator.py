"""
hospital_generator.py  (constraint-aware)
================================================
Synthetic data generator for hospital_db.
Populates all 17 tables in topological dependency order.

Constraint-aware patches vs the prior version (targets the actual
remaining violation drivers — verified against validate_repair.py, not
just the prior docstring's claims):

  1. gen_admissions — department & admission_type now driven by patient
     age (newborn / pediatric / adult buckets), eliminating most of
     Group 2 (age-based) violations at the source.
  2. gen_admissions — room selection now respects patient_condition via
     CONDITION_ROOM_MAP, eliminating most of Group 4's
     condition_room_mismatch violations.
  3. gen_diagnoses — sample_diagnosis() is now called with a department
     filter AND a gender/age impossible-code filter (mirrors
     repair_diagnoses' resample loop), eliminating most of Group 5.
  4. gen_billing — bill_date is now anchored to discharge_date when one
     exists, eliminating most of Group 1's bill_before_discharge.

NOT changed (already correct previously, verified by reading the code):
  - diagnosis/procedure/medication/test/triage dates were already
    constrained to the admission window.
  - admitting doctor and room were already matched to the admission
    department.

Still left to repair (by design — true edge cases, not systemic):
  - registered_date for newborn patients (patients are generated before
    admissions exist, so this can't be known at patient-generation time
    without restructuring the pipeline order; repair_age fixes it cheaply).
  - condition/room mismatches in departments that lack a room of the
    condition-appropriate type (falls back to any room in-department).

Prerequisites:
    pip install sqlalchemy pymysql faker numpy pandas
    MySQL running with hospital_db schema already created (hospital_db.sql)
    icd10_diagnoses.py in the same directory

Usage (Jupyter):
    exec(open('hospital_generator.py').read())
    main('small')   # or 'medium' / 'large'
"""

import sys
import random
import numpy as np
import pandas as pd
from faker import Faker
from faker.providers import ssn as ssn_provider, BaseProvider, person as person_provider
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine, text
from collections import defaultdict

from icd10_diagnoses import sample_diagnosis


# =============================================================================
# CONFIGURATION
# =============================================================================

DB_URL = "mysql+pymysql://root:@localhost/hospital_db"

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

PAYER_COVERAGE = {
    "Medicare":             0.80,
    "Medicaid":             0.72,
    "Private Insurance":    0.85,
    "Self-Pay":             0.00,
    "Workers Compensation": 0.90,
    "CHIP":                 0.75,
}

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

ADMISSION_STATUSES  = ['Admitted', 'Discharged', 'Scheduled', 'Cancelled']
ADMISSION_STATUS_P  = [0.20, 0.60, 0.15, 0.05]

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
NEWBORN_DEPT_POOL   = ['DEP-008', 'DEP-009']
PEDIATRIC_DEPT_POOL = ['DEP-008', 'DEP-001', 'DEP-002']

NEWBORN_ADM_TYPES   = ['Newborn', 'Emergency', 'Urgent']
NEWBORN_ADM_TYPE_P  = [0.60, 0.25, 0.15]

_non_newborn_pairs   = [(t, p) for t, p in zip(ADMISSION_TYPES, ADMISSION_TYPE_P) if t != 'Newborn']
NON_NEWBORN_TYPES    = [t for t, _ in _non_newborn_pairs]
_non_newborn_p_raw   = np.array([p for _, p in _non_newborn_pairs])
NON_NEWBORN_TYPE_P   = list(_non_newborn_p_raw / _non_newborn_p_raw.sum())

# ── Condition → allowed room types ──────────────────────────────────────────
# Must match CONDITION_ROOM_MAP in validate_repair.py.
CONDITION_ROOM_MAP = {
    'Intensive': ['ICU', 'NICU'],
    'Maximum':   ['ICU', 'NICU', 'Private', 'Isolation'],
    'Moderate':  ['Standard', 'Private'],
    'Minimal':   ['Standard', 'Recovery', 'Private'],
}

# ── ICD-10 codes that are biologically impossible for certain genders/ages ──
# Must match MALE_IMPOSSIBLE_CODES / FEMALE_IMPOSSIBLE_CODES / NEWBORN_ONLY_CODES
# in validate_repair.py.
MALE_IMPOSSIBLE_CODES   = {'O80', 'O34.21', 'O09.90', 'O20.0', 'C50.919'}
FEMALE_IMPOSSIBLE_CODES = {'C61'}
NEWBORN_ONLY_CODES      = {'Z38.00', 'P07.30'}


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
    end   = dis_dt.date() if dis_dt else date.today()
    return random_date_between(start, end)


def datetime_within_admission(adm_dt: datetime, dis_dt: datetime = None) -> datetime:
    """Return a random datetime between admission and discharge (or now)."""
    end = dis_dt if dis_dt else datetime.now()
    return random_datetime_between(adm_dt, end)


def gender_name(gender: str) -> str:
    if gender == 'M':
        return fake.first_name_male()
    elif gender == 'F':
        return fake.first_name_female()
    return fake.first_name_nonbinary()


def age_from_dob(dob: date) -> int:
    return int((date.today() - dob).days / 365.2425)


def poisson_count(avg: float) -> int:
    return max(0, np.random.poisson(avg))


def execute_batch(conn, sql: str, rows: list):
    if rows:
        conn.execute(text(sql), rows)


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
    reg_end     = date.today()
    rows        = []
    patient_ids = []

    for _ in range(cfg['patients']):
        pid     = gen_id("PAT")
        gender  = np.random.choice(['M', 'F', 'NB'], p=[0.48, 0.48, 0.04])
        dob     = fake.date_of_birth(minimum_age=0, maximum_age=100)
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
            "registered_date": random_date_between(reg_start, reg_end),
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

    for _ in range(cfg['doctors']):
        did       = gen_id("DOC")
        gender    = np.random.choice(['M', 'F', 'NB'], p=[0.55, 0.42, 0.03])
        specialty = random.choice(DOCTOR_SPECIALTIES)
        dept_id   = random.choice(SPECIALTY_TO_DEPARTMENT.get(specialty, dept_ids))

        rows.append({
            "doctor_id":     did,
            "first_name":    gender_name(gender),
            "last_name":     fake.last_name(),
            "birth_date":    fake.date_of_birth(minimum_age=28, maximum_age=70),
            "gender":        gender,
            "contact":       fake.phone_number()[:20],
            "specialty":     specialty,
            "department_id": dept_id,
            "hire_date":     random_date_between(hire_start, date.today()),
        })
        doctor_ids.append(did)

    # Guarantee at least one doctor per department (mirrors gen_rooms'
    # guarantee below) — otherwise departments with no doctors produce
    # doctor_dept_mismatch violations that repair_department can never
    # fix, since it has no doctor in that department to reassign to.
    assigned_depts = {r["department_id"] for r in rows}
    missing_depts  = [d for d in dept_ids if d not in assigned_depts]

    dept_to_specialties = defaultdict(list)
    for specialty, depts in SPECIALTY_TO_DEPARTMENT.items():
        for d in depts:
            dept_to_specialties[d].append(specialty)

    for dept_id in missing_depts:
        did       = gen_id("DOC")
        gender    = np.random.choice(['M', 'F', 'NB'], p=[0.55, 0.42, 0.03])
        specialty = random.choice(dept_to_specialties.get(dept_id) or DOCTOR_SPECIALTIES)

        rows.append({
            "doctor_id":     did,
            "first_name":    gender_name(gender),
            "last_name":     fake.last_name(),
            "birth_date":    fake.date_of_birth(minimum_age=28, maximum_age=70),
            "gender":        gender,
            "contact":       fake.phone_number()[:20],
            "specialty":     specialty,
            "department_id": dept_id,
            "hire_date":     random_date_between(hire_start, date.today()),
        })
        doctor_ids.append(did)
        print(f"    Guaranteed doctor added for {dept_id}")

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

        rows.append({
            "nurse_id":      nid,
            "first_name":    gender_name(gender),
            "last_name":     fake.last_name(),
            "birth_date":    fake.date_of_birth(minimum_age=22, maximum_age=65),
            "gender":        gender,
            "contact":       fake.phone_number()[:20],
            "position":      position,
            "department_id": dept_id,
            "hire_date":     random_date_between(hire_start, date.today()),
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
            "hire_date":     random_date_between(hire_start, date.today()),
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


def _load_patient_ages(conn) -> dict:
    """{patient_id: age} lookup, used to drive age-aware admissions."""
    result = conn.execute(text("SELECT patient_id, age FROM patients"))
    return {row[0]: row[1] for row in result}


def gen_admissions(conn, cfg: dict, patient_ids: list,
                   doctor_ids: list, dept_ids: list,
                   patient_age_map: dict) -> list:
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

    # Build dept -> doctor, dept -> room, and dept -> room_type -> room lookups
    result = conn.execute(text("SELECT doctor_id, department_id FROM doctors"))
    dept_doctor_map = defaultdict(list)
    for row in result:
        dept_doctor_map[row[1]].append(row[0])

    result = conn.execute(text("SELECT room_id, department_id, room_type FROM rooms"))
    dept_room_map      = defaultdict(list)
    dept_room_type_map = defaultdict(lambda: defaultdict(list))
    for row in result:
        dept_room_map[row[1]].append(row[0])
        dept_room_type_map[row[1]][row[2]].append(row[0])

    # Adult pool excludes Pediatrics so adults never land in DEP-008
    adult_dept_pool = [d for d in dept_ids if d != 'DEP-008']

    adm_start = datetime(2020, 1, 1)
    adm_end   = datetime.now()
    rows      = []
    adm_ids   = []

    for _ in range(cfg['admissions']):
        aid        = gen_id("ADM")
        patient_id = random.choice(patient_ids)
        age        = patient_age_map.get(patient_id, 30)

        # Department & admission_type driven by patient age
        if age == 0:
            dept_id  = random.choice(NEWBORN_DEPT_POOL)
            adm_type = np.random.choice(NEWBORN_ADM_TYPES, p=NEWBORN_ADM_TYPE_P)
        elif age <= 17:
            dept_id  = random.choice(PEDIATRIC_DEPT_POOL)
            adm_type = np.random.choice(NON_NEWBORN_TYPES, p=NON_NEWBORN_TYPE_P)
        else:
            dept_id  = random.choice(adult_dept_pool)
            adm_type = np.random.choice(NON_NEWBORN_TYPES, p=NON_NEWBORN_TYPE_P)

        status    = np.random.choice(ADMISSION_STATUSES, p=ADMISSION_STATUS_P)
        adm_dt    = random_datetime_between(adm_start, adm_end)
        condition = np.random.choice(
                        ['Minimal', 'Moderate', 'Maximum', 'Intensive'],
                        p=[0.15, 0.40, 0.30, 0.15]
                    )

        # Doctor matched to admission department
        dept_docs = dept_doctor_map.get(dept_id, doctor_ids)
        doc_id    = random.choice(dept_docs if dept_docs else doctor_ids)

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

        if status == 'Discharged':
            los    = max(1, int(np.random.exponential(scale=5)))
            dis_dt = min(adm_dt + timedelta(days=los), datetime.now())
            dis_dsp = np.random.choice(
                          DISCHARGE_DISPOSITIONS['options'],
                          p=DISCHARGE_DISPOSITIONS['probs']
                      )
        else:
            los, dis_dt, dis_dsp = None, None, 'Still Admitted'

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
    {admission_id: {dept_name, gender, age}} — used by gen_diagnoses
    to sample department-appropriate, gender/age-valid ICD-10 codes.
    """
    result = conn.execute(text("""
        SELECT a.admission_id, dpt.dep_name, p.gender, p.age
        FROM admissions a
        JOIN departments dpt ON a.department_id = dpt.department_id
        JOIN patients p      ON a.patient_id    = p.patient_id
    """))
    info_map = {}
    for row in result:
        info_map[row[0]] = {"dept_name": row[1], "gender": row[2], "age": row[3]}
    return info_map


def gen_triage(conn, admission_ids: list, nurse_ids: list,
               adm_dt_map: dict, dis_dt_map: dict):
    target = [a for a in admission_ids if random.random() < 0.80]
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

    rows = []
    for adm_id in target:
        adm_dt = adm_dt_map.get(adm_id, datetime.now())
        dis_dt = dis_dt_map.get(adm_id)
        rows.append({
            "triage_id":         gen_id("TRI"),
            "admission_id":      adm_id,
            "nurse_id":          random.choice(nurse_ids),
            "triage_datetime":   datetime_within_admission(adm_dt, dis_dt),
            "bp_systolic":       random.randint(90, 180),
            "bp_diastolic":      random.randint(50, 110),
            "heart_rate":        random.randint(50, 140),
            "temperature":       round(random.uniform(97.0, 103.5), 1),
            "respiratory_rate":  random.randint(12, 28),
            "oxygen_saturation": random.randint(88, 100),
            "height_cm":         random.randint(140, 200),
            "weight_kg":         round(random.uniform(45.0, 150.0), 1),
            "pain_level":        random.randint(0, 10),
            "chief_complaint":   random.choice(CHIEF_COMPLAINTS),
            "acuity_level":      np.random.choice(
                                     [1, 2, 3, 4, 5],
                                     p=[0.05, 0.20, 0.40, 0.25, 0.10]
                                 ),
        })

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} triage records inserted")


def gen_diagnoses(conn, cfg: dict, admission_ids: list, doctor_ids: list,
                  adm_dt_map: dict, dis_dt_map: dict, adm_info_map: dict):
    print(f"  Generating diagnoses...")
    sql = """INSERT INTO diagnoses
             (diagnosis_id, admission_id, doctor_id, icd10_code,
              diagnosis_date, diagnosis_type)
             VALUES (:diagnosis_id, :admission_id, :doctor_id, :icd10_code,
                     :diagnosis_date, :diagnosis_type)"""

    rows = []
    for adm_id in admission_ids:
        adm_dt = adm_dt_map.get(adm_id, datetime.now())
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
            rows.append({
                "diagnosis_id":   gen_id("DXX"),
                "admission_id":   adm_id,
                "doctor_id":      random.choice(doctor_ids),
                "icd10_code":     dx['icd10_code'],
                "diagnosis_date": date_within_admission(adm_dt, dis_dt),
                "diagnosis_type": dx_type,
            })

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} diagnoses inserted")


def gen_patient_procedures(conn, cfg: dict, admission_ids: list,
                           doctor_ids: list, adm_dt_map: dict,
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
        adm_dt = adm_dt_map.get(adm_id, datetime.now())
        dis_dt = dis_dt_map.get(adm_id)
        count  = poisson_count(cfg['avg_procedures'])

        for _ in range(count):
            ppid = gen_id("PRP")
            rows.append({
                "patient_procedure_id": ppid,
                "admission_id":         adm_id,
                "procedure_id":         random.choice(proc_ids),
                "doctor_id":            random.choice(doctor_ids),
                "procedure_date":       datetime_within_admission(adm_dt, dis_dt),
                "procedure_status":     np.random.choice(pp_statuses, p=pp_status_p),
                "notes":                None,
            })
            pp_ids.append(ppid)

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} patient procedures inserted")
    return pp_ids


def gen_medications(conn, cfg: dict, admission_ids: list, doctor_ids: list,
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
        adm_dt = adm_dt_map.get(adm_id, datetime.now())
        dis_dt = dis_dt_map.get(adm_id)
        count  = poisson_count(cfg['avg_medications'])

        for _ in range(count):
            med        = random.choice(MEDICATIONS_LIST)
            start      = date_within_admission(adm_dt, dis_dt)
            med_status = np.random.choice(med_statuses, p=med_status_p)
            end_dt     = None
            if med_status in ['Discontinued', 'Completed']:
                window_end = dis_dt.date() if dis_dt else date.today()
                end_dt     = random_date_between(start, window_end)

            rows.append({
                "medication_id": gen_id("MED"),
                "admission_id":  adm_id,
                "doctor_id":     random.choice(doctor_ids),
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
                      doctor_ids: list, nurse_ids: list,
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
        adm_dt = adm_dt_map.get(adm_id, datetime.now())
        dis_dt = dis_dt_map.get(adm_id)
        count  = poisson_count(cfg['avg_tests'])

        for _ in range(count):
            tid           = gen_id("TST")
            category      = random.choice(categories)
            test_nm, cost = random.choice(test_catalog[category])
            test_dt       = datetime_within_admission(adm_dt, dis_dt)
            result        = np.random.choice(result_opts, p=result_p)

            if result != 'Pending':
                max_res  = dis_dt.date() if dis_dt else date.today()
                res_date = random_date_between(
                    test_dt.date(), max(test_dt.date(), max_res)
                )
            else:
                res_date = None

            rows.append({
                "test_id":       tid,
                "admission_id":  adm_id,
                "doctor_id":     random.choice(doctor_ids),
                "nurse_id":      random.choice(nurse_ids) if random.random() > 0.3 else None,
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


def gen_staff_shifts(conn, cfg: dict, doctor_ids: list,
                     nurse_ids: list, employee_ids: list, dept_ids: list):
    print(f"  Generating staff shifts...")
    sql = """INSERT INTO staff_shifts
             (shift_id, staff_id, staff_type, department_id,
              shift_date, shift_type, hours_worked)
             VALUES (:shift_id, :staff_id, :staff_type, :department_id,
                     :shift_date, :shift_type, :hours_worked)"""

    shift_start = date(2023, 1, 1)
    shift_end   = date.today()
    n           = cfg['shifts_per_staff']
    rows        = []

    staff_pool = (
        [(did, 'Doctor')   for did in doctor_ids] +
        [(nid, 'Nurse')    for nid in nurse_ids]  +
        [(eid, 'Employee') for eid in employee_ids]
    )

    for staff_id, staff_type in staff_pool:
        for _ in range(n):
            rows.append({
                "shift_id":      gen_id("SHF"),
                "staff_id":      staff_id,
                "staff_type":    staff_type,
                "department_id": random.choice(dept_ids),
                "shift_date":    random_date_between(shift_start, shift_end),
                "shift_type":    random.choice(SHIFT_TYPES),
                "hours_worked":  random.choice([8.0, 10.0, 12.0]),
            })

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} staff shifts inserted")


def gen_billing(conn, patient_ids_map: dict, payer_ids: list, dis_dt_map: dict) -> dict:
    print(f"  Generating billing records...")
    sql = """INSERT INTO billing
             (bill_id, admission_id, patient_id, payer_id, bill_date,
              due_date, total_amount, insurance_covered, patient_responsibility,
              payment_status, payment_date)
             VALUES (:bill_id, :admission_id, :patient_id, :payer_id, :bill_date,
                     :due_date, :total_amount, :insurance_covered,
                     :patient_responsibility, :payment_status, :payment_date)"""

    pmt_statuses = ['Pending', 'Partial', 'Paid', 'Denied', 'Write-Off']
    pmt_status_p = [0.20, 0.15, 0.50, 0.10, 0.05]
    rows         = []
    bill_map     = {}

    for adm_id, pat_id in patient_ids_map.items():
        bid        = gen_id("BIL")
        payer      = random.choice(PAYERS_DATA)
        payer_id   = payer["payer_id"]
        payer_type = payer["payer_type"]
        coverage   = PAYER_COVERAGE[payer_type]
        total      = round(random.uniform(500, 45000), 2)
        ins_cov    = round(total * coverage, 2)
        pat_resp   = round(total - ins_cov, 2)

        # Anchor bill_date to discharge_date when one exists, so
        # billing never predates discharge (Group 1 bill_before_discharge)
        dis_dt = dis_dt_map.get(adm_id)
        if dis_dt:
            window_start = dis_dt.date() if isinstance(dis_dt, datetime) else dis_dt
            window_end   = max(window_start, min(window_start + timedelta(days=90), date.today()))
            bill_dt      = random_date_between(window_start, window_end)
        else:
            bill_dt = fake.date_between(start_date='-3y', end_date='today')

        due_dt     = bill_dt + timedelta(days=30)
        pmt_status = np.random.choice(pmt_statuses, p=pmt_status_p)
        pmt_date   = (bill_dt + timedelta(days=random.randint(5, 90))) \
                     if pmt_status == 'Paid' else None

        rows.append({
            "bill_id":                bid,
            "admission_id":           adm_id,
            "patient_id":             pat_id,
            "payer_id":               payer_id,
            "bill_date":              bill_dt,
            "due_date":               due_dt,
            "total_amount":           total,
            "insurance_covered":      ins_cov,
            "patient_responsibility": pat_resp,
            "payment_status":         pmt_status,
            "payment_date":           pmt_date,
        })
        bill_map[bid] = payer_type

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} billing records inserted")
    return bill_map


def gen_billing_line_items(conn, bill_map: dict,
                           pp_ids: list, test_ids: list):
    print(f"  Generating billing line items...")
    sql = """INSERT INTO billing_line_items
             (line_item_id, bill_id, item_type, patient_procedure_id,
              test_id, description, quantity, unit_cost, total_cost, covered_amount)
             VALUES (:line_item_id, :bill_id, :item_type, :patient_procedure_id,
                     :test_id, :description, :quantity, :unit_cost,
                     :total_cost, :covered_amount)"""

    item_types  = ['Procedure', 'Medication', 'Room', 'Lab', 'Consultation']
    item_type_p = [0.25, 0.20, 0.25, 0.20, 0.10]
    pp_pool     = pp_ids   if pp_ids   else [None]
    tst_pool    = test_ids if test_ids else [None]

    room_descs   = ['Standard Room (per day)', 'Private Room (per day)',
                    'ICU Room (per day)', 'ER Bay (per visit)']
    consult_desc = ['Specialist Consultation', 'Initial Consultation',
                    'Follow-up Consultation', 'Telemedicine Consultation']

    rows = []
    for bill_id, payer_type in bill_map.items():
        coverage = PAYER_COVERAGE[payer_type]
        n_items  = random.randint(2, 6)

        for _ in range(n_items):
            item_type = np.random.choice(item_types, p=item_type_p)
            qty       = 1
            pp_id     = None
            t_id      = None

            if item_type == 'Procedure':
                pp_id       = random.choice(pp_pool)
                proc        = random.choice(PROCEDURES_DATA)
                description = proc["procedure_name"]
                unit_cost   = round(proc["base_cost"] * random.uniform(0.9, 1.1), 2)
            elif item_type == 'Lab':
                t_id        = random.choice(tst_pool)
                description = 'Laboratory test'
                unit_cost   = round(random.uniform(80, 2500), 2)
            elif item_type == 'Medication':
                med         = random.choice(MEDICATIONS_LIST)
                description = f"{med['drug_name']} {med['dosage']}"
                qty         = random.randint(1, 30)
                unit_cost   = round(random.uniform(5, 250), 2)
            elif item_type == 'Room':
                description = random.choice(room_descs)
                qty         = random.randint(1, 14)
                unit_cost   = round(random.uniform(800, 3500), 2)
            else:
                description = random.choice(consult_desc)
                unit_cost   = round(random.uniform(200, 800), 2)

            total_cost     = round(unit_cost * qty, 2)
            covered_amount = round(total_cost * coverage, 2)

            rows.append({
                "line_item_id":         gen_id("LIN"),
                "bill_id":              bill_id,
                "item_type":            item_type,
                "patient_procedure_id": pp_id,
                "test_id":              t_id,
                "description":          description,
                "quantity":             qty,
                "unit_cost":            unit_cost,
                "total_cost":           total_cost,
                "covered_amount":       covered_amount,
            })

    execute_batch(conn, sql, rows)
    print(f"    {len(rows)} billing line items inserted")


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

        patient_age_map = _load_patient_ages(conn)

        # ── Domain 3: Clinical ──────────────────────────────────────────────
        print("\n[ Domain 3 ] Clinical")
        admission_ids = gen_admissions(
            conn, cfg, patient_ids, doctor_ids, dept_ids, patient_age_map
        )

        adm_dt_map, dis_dt_map = _load_admission_windows(conn)
        adm_info_map = _load_admission_clinical_info(conn)

        result = conn.execute(text(
            "SELECT admission_id, patient_id FROM admissions "
            "WHERE admission_status IN ('Admitted','Discharged')"
        ))
        adm_patient_map = {row[0]: row[1] for row in result}

        gen_triage(conn, admission_ids, nurse_ids, adm_dt_map, dis_dt_map)
        gen_diagnoses(
            conn, cfg, admission_ids, doctor_ids, adm_dt_map, dis_dt_map, adm_info_map
        )
        pp_ids = gen_patient_procedures(
            conn, cfg, admission_ids, doctor_ids, adm_dt_map, dis_dt_map
        )
        gen_medications(conn, cfg, admission_ids, doctor_ids, adm_dt_map, dis_dt_map)
        test_ids = gen_medical_tests(
            conn, cfg, admission_ids, doctor_ids, nurse_ids, adm_dt_map, dis_dt_map
        )
        gen_staff_shifts(conn, cfg, doctor_ids, nurse_ids, employee_ids, dept_ids)
        conn.commit()

        # ── Domain 4: Financial ─────────────────────────────────────────────
        print("\n[ Domain 4 ] Financial")
        bill_map = gen_billing(conn, adm_patient_map, payer_ids, dis_dt_map)
        gen_billing_line_items(conn, bill_map, pp_ids, test_ids)
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
