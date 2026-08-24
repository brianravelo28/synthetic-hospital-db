-- =============================================================================
-- hospital_db.sql
-- Synthetic Hospital Database — DDL
-- =============================================================================
-- Tables:          17
-- Engine:          InnoDB (required for foreign key enforcement)
-- Charset:         utf8mb4 (supports full Unicode, emoji-safe)
-- Collation:       utf8mb4_unicode_ci
--
-- Creation order follows topological dependency:
--   Reference tables first (departments, payers, procedures)
--   Staff & facilities second (doctors, nurses, employees, rooms)
--   Clinical third (patients, admissions, triage, diagnoses,
--                   patient_procedures, medications, medical_tests,
--                   staff_shifts)
--   Financial last (billing, billing_line_items)
--
-- To run:
--   mysql -u root -p < hospital_db.sql
--   or paste into MySQL Workbench / DBeaver
-- =============================================================================

-- Drop and recreate the database cleanly
DROP DATABASE IF EXISTS hospital_db;
CREATE DATABASE hospital_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE hospital_db;

-- Disable FK checks during creation to allow flexible ordering if needed
SET FOREIGN_KEY_CHECKS = 0;


-- =============================================================================
-- DOMAIN 1 — REFERENCE / LOOKUP TABLES
-- No foreign key dependencies — generate data for these first
-- =============================================================================

-- -----------------------------------------------------------------------------
-- departments
-- Hospital department catalog. Referenced by almost every other table.
-- bed_capacity drives hospital size configuration in the Python generators.
-- NOTE: head_doctor_id is intentionally excluded from v1 to avoid a circular
--       dependency. Add via ALTER TABLE after doctors are populated in v2.
-- -----------------------------------------------------------------------------
CREATE TABLE departments (
    department_id       VARCHAR(10)     NOT NULL,
    dep_name            VARCHAR(50)     NOT NULL,
    floor_number        TINYINT         NOT NULL,
    bed_capacity        SMALLINT        NOT NULL        COMMENT 'Total beds in this department',

    CONSTRAINT pk_departments       PRIMARY KEY (department_id),
    CONSTRAINT uq_dep_name          UNIQUE (dep_name),
    CONSTRAINT chk_bed_capacity     CHECK (bed_capacity > 0),
    CONSTRAINT chk_floor_number     CHECK (floor_number >= 0)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Hospital department catalog';


-- -----------------------------------------------------------------------------
-- payers
-- Insurance companies and payer type classifications.
-- payer_type drives coverage percentage logic in billing generators.
-- -----------------------------------------------------------------------------
CREATE TABLE payers (
    payer_id            VARCHAR(10)     NOT NULL,
    payer_name          VARCHAR(100)    NOT NULL,
    payer_type          ENUM(
                            'Medicare',
                            'Medicaid',
                            'Private Insurance',
                            'Self-Pay',
                            'Workers Compensation',
                            'CHIP'
                        )               NOT NULL,
    contact_phone       VARCHAR(20)     NULL,

    CONSTRAINT pk_payers            PRIMARY KEY (payer_id)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Insurance companies and payer types';


-- -----------------------------------------------------------------------------
-- procedures
-- Procedure catalog — the menu of services the hospital offers.
-- Acts as a lookup table for patient_procedures and billing_line_items.
-- procedure_code mimics CPT (Current Procedural Terminology) format.
-- base_cost is the list price before insurance negotiation.
-- -----------------------------------------------------------------------------
CREATE TABLE procedures (
    procedure_id        VARCHAR(10)     NOT NULL,
    procedure_code      VARCHAR(10)     NOT NULL,
    procedure_name      VARCHAR(100)    NOT NULL,
    department_id       VARCHAR(10)     NOT NULL,
    base_cost           DECIMAL(10,2)   NOT NULL,
    duration_minutes    SMALLINT        NULL            COMMENT 'Estimated procedure duration',

    CONSTRAINT pk_procedures        PRIMARY KEY (procedure_id),
    CONSTRAINT uq_procedure_code    UNIQUE (procedure_code),
    CONSTRAINT fk_proc_department   FOREIGN KEY (department_id)
                                        REFERENCES departments (department_id)
                                        ON DELETE RESTRICT
                                        ON UPDATE CASCADE,
    CONSTRAINT chk_proc_cost        CHECK (base_cost >= 0),
    CONSTRAINT chk_duration         CHECK (duration_minutes IS NULL OR duration_minutes > 0)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Hospital procedure catalog with CPT-style codes';


-- =============================================================================
-- DOMAIN 2 — STAFF & FACILITIES
-- Depend on departments — generate after reference tables
-- =============================================================================

-- -----------------------------------------------------------------------------
-- patients
-- Core patient demographics. No foreign key dependencies.
-- registered_date = first time patient appears in system (not admission date).
-- age is stored (not computed) for query performance; generators must keep it
-- consistent with birth_date.
-- -----------------------------------------------------------------------------
CREATE TABLE patients (
    patient_id          VARCHAR(15)     NOT NULL,
    first_name          VARCHAR(50)     NOT NULL,
    last_name           VARCHAR(50)     NOT NULL,
    ssn                 VARCHAR(11)     NOT NULL        COMMENT 'Format: XXX-XX-XXXX',
    birth_date          DATE            NOT NULL,
    age                 TINYINT         NOT NULL,
    gender              ENUM('M','F','NB')  NOT NULL,
    blood_type          ENUM(
                            'A+','A-',
                            'B+','B-',
                            'AB+','AB-',
                            'O+','O-'
                        )               NULL,
    phone               VARCHAR(20)     NULL,
    email               VARCHAR(100)    NULL,
    address             VARCHAR(100)    NULL,
    city                VARCHAR(50)     NULL,
    state               VARCHAR(3)      NULL,
    zip_code            VARCHAR(10)     NULL,
    country             VARCHAR(50)     NULL            DEFAULT 'USA',
    registered_date     DATE            NOT NULL,

    CONSTRAINT pk_patients          PRIMARY KEY (patient_id),
    CONSTRAINT uq_patient_ssn       UNIQUE (ssn),
    CONSTRAINT chk_patient_age      CHECK (age >= 0 AND age <= 130)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Patient demographics and contact information';

-- Index for common lookups by name
CREATE INDEX idx_patients_last_name ON patients (last_name);
CREATE INDEX idx_patients_dob       ON patients (birth_date);


-- -----------------------------------------------------------------------------
-- doctors
-- Clinical physicians. department_id reflects primary department assignment.
-- specialty matches the doctor_specialities list in the Python generators.
-- -----------------------------------------------------------------------------
CREATE TABLE doctors (
    doctor_id           VARCHAR(15)     NOT NULL,
    first_name          VARCHAR(50)     NOT NULL,
    last_name           VARCHAR(50)     NOT NULL,
    birth_date          DATE            NULL,
    gender              ENUM('M','F','NB')  NULL,
    contact             VARCHAR(20)     NULL,
    specialty           VARCHAR(50)     NOT NULL,
    department_id       VARCHAR(10)     NOT NULL,
    hire_date           DATE            NOT NULL,

    CONSTRAINT pk_doctors           PRIMARY KEY (doctor_id),
    CONSTRAINT fk_doc_department    FOREIGN KEY (department_id)
                                        REFERENCES departments (department_id)
                                        ON DELETE RESTRICT
                                        ON UPDATE CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Clinical physician staff';

CREATE INDEX idx_doctors_department ON doctors (department_id);
CREATE INDEX idx_doctors_specialty  ON doctors (specialty);


-- -----------------------------------------------------------------------------
-- nurses
-- Nursing staff. department_id reflects primary assignment.
-- position matches the nurse_positions list in the Python generators.
-- -----------------------------------------------------------------------------
CREATE TABLE nurses (
    nurse_id            VARCHAR(15)     NOT NULL,
    first_name          VARCHAR(50)     NOT NULL,
    last_name           VARCHAR(50)     NOT NULL,
    birth_date          DATE            NULL,
    gender              ENUM('M','F','NB')  NULL,
    contact             VARCHAR(20)     NULL,
    position            VARCHAR(50)     NOT NULL,
    department_id       VARCHAR(10)     NOT NULL,
    hire_date           DATE            NOT NULL,

    CONSTRAINT pk_nurses            PRIMARY KEY (nurse_id),
    CONSTRAINT fk_nurse_department  FOREIGN KEY (department_id)
                                        REFERENCES departments (department_id)
                                        ON DELETE RESTRICT
                                        ON UPDATE CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Nursing staff';

CREATE INDEX idx_nurses_department  ON nurses (department_id);
CREATE INDEX idx_nurses_position    ON nurses (position);


-- -----------------------------------------------------------------------------
-- employees
-- Non-clinical staff: admin, billing, IT, facilities, etc.
-- department_id is nullable for roles that span departments (e.g. IT, HR).
-- -----------------------------------------------------------------------------
CREATE TABLE employees (
    employee_id         VARCHAR(15)     NOT NULL,
    first_name          VARCHAR(50)     NOT NULL,
    last_name           VARCHAR(50)     NOT NULL,
    gender              ENUM('M','F','NB')  NULL,
    position            VARCHAR(50)     NOT NULL,
    department_id       VARCHAR(10)     NULL            COMMENT 'NULL for hospital-wide roles',
    contact             VARCHAR(20)     NULL,
    salary              DECIMAL(10,2)   NULL,
    hire_date           DATE            NOT NULL,

    CONSTRAINT pk_employees         PRIMARY KEY (employee_id),
    CONSTRAINT fk_emp_department    FOREIGN KEY (department_id)
                                        REFERENCES departments (department_id)
                                        ON DELETE SET NULL
                                        ON UPDATE CASCADE,
    CONSTRAINT chk_salary           CHECK (salary IS NULL OR salary >= 0)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Non-clinical hospital staff';


-- -----------------------------------------------------------------------------
-- rooms
-- Physical rooms within the hospital.
-- room_type drives assignment logic: ICU patients go to ICU rooms, etc.
-- status is updated by the generators as admissions are created.
-- -----------------------------------------------------------------------------
CREATE TABLE rooms (
    room_id             VARCHAR(15)     NOT NULL,
    room_number         VARCHAR(10)     NOT NULL,
    room_type           ENUM(
                            'Standard',
                            'Private',
                            'ICU',
                            'NICU',
                            'OR',
                            'ER',
                            'Recovery',
                            'Isolation'
                        )               NOT NULL,
    floor_number        TINYINT         NOT NULL,
    bed_capacity        TINYINT         NOT NULL        DEFAULT 1,
    department_id       VARCHAR(10)     NOT NULL,
    status              ENUM(
                            'Available',
                            'Occupied',
                            'Maintenance'
                        )               NOT NULL        DEFAULT 'Available',

    CONSTRAINT pk_rooms             PRIMARY KEY (room_id),
    CONSTRAINT fk_room_department   FOREIGN KEY (department_id)
                                        REFERENCES departments (department_id)
                                        ON DELETE RESTRICT
                                        ON UPDATE CASCADE,
    CONSTRAINT chk_bed_cap_room     CHECK (bed_capacity > 0)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Hospital rooms and bed capacity';

CREATE INDEX idx_rooms_department   ON rooms (department_id);
CREATE INDEX idx_rooms_status       ON rooms (status);


-- =============================================================================
-- DOMAIN 3 — CLINICAL
-- Depend on patients, staff, and facilities
-- =============================================================================

-- -----------------------------------------------------------------------------
-- admissions
-- Central clinical table — nearly everything else hangs off this.
-- admission_status incorporates the scheduled visits concept:
--   Scheduled = future appointment, no room assigned yet
--   Admitted   = currently inpatient
--   Discharged = complete
--   Cancelled  = appointment or elective admission cancelled
-- room_id and discharge_date are nullable to support Scheduled records.
-- length_of_stay is stored (redundant with date diff) for Tableau performance.
-- -----------------------------------------------------------------------------
CREATE TABLE admissions (
    admission_id            VARCHAR(15)     NOT NULL,
    patient_id              VARCHAR(15)     NOT NULL,
    admitting_doctor_id     VARCHAR(15)     NOT NULL,
    department_id           VARCHAR(10)     NOT NULL,
    room_id                 VARCHAR(15)     NULL            COMMENT 'NULL for Scheduled admissions',
    admission_date          DATETIME        NOT NULL,
    discharge_date          DATETIME        NULL            COMMENT 'NULL if still admitted or scheduled',
    admission_type          ENUM(
                                'Emergency',
                                'Elective',
                                'Urgent',
                                'Newborn',
                                'Scheduled'
                            )               NOT NULL,
    admission_status        ENUM(
                                'Scheduled',
                                'Admitted',
                                'Discharged',
                                'Cancelled'
                            )               NOT NULL        DEFAULT 'Scheduled',
    discharge_disposition   ENUM(
                                'Home',
                                'Transfer',
                                'Skilled Nursing Facility',
                                'Deceased',
                                'AMA',
                                'Still Admitted'
                            )               NOT NULL        DEFAULT 'Still Admitted',
    patient_condition       ENUM(
                                'Minimal',
                                'Moderate',
                                'Maximum',
                                'Intensive'
                            )               NOT NULL,
    length_of_stay          SMALLINT        NULL            COMMENT 'Days — set on discharge',

    CONSTRAINT pk_admissions            PRIMARY KEY (admission_id),
    CONSTRAINT fk_adm_patient           FOREIGN KEY (patient_id)
                                            REFERENCES patients (patient_id)
                                            ON DELETE RESTRICT
                                            ON UPDATE CASCADE,
    CONSTRAINT fk_adm_doctor            FOREIGN KEY (admitting_doctor_id)
                                            REFERENCES doctors (doctor_id)
                                            ON DELETE RESTRICT
                                            ON UPDATE CASCADE,
    CONSTRAINT fk_adm_department        FOREIGN KEY (department_id)
                                            REFERENCES departments (department_id)
                                            ON DELETE RESTRICT
                                            ON UPDATE CASCADE,
    CONSTRAINT fk_adm_room              FOREIGN KEY (room_id)
                                            REFERENCES rooms (room_id)
                                            ON DELETE SET NULL
                                            ON UPDATE CASCADE,
    CONSTRAINT chk_discharge_after_adm CHECK (
                                            discharge_date IS NULL
                                            OR discharge_date >= admission_date
                                        ),
    CONSTRAINT chk_los                  CHECK (length_of_stay IS NULL OR length_of_stay >= 0)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Patient admissions including scheduled visits';

CREATE INDEX idx_adm_patient        ON admissions (patient_id);
CREATE INDEX idx_adm_doctor         ON admissions (admitting_doctor_id);
CREATE INDEX idx_adm_department     ON admissions (department_id);
CREATE INDEX idx_adm_dates          ON admissions (admission_date, discharge_date);
CREATE INDEX idx_adm_status         ON admissions (admission_status);


-- -----------------------------------------------------------------------------
-- triage
-- Vital signs recorded at intake. One triage record per admission.
-- Vital sign ranges are constrained to clinically plausible values.
-- acuity_level uses the Emergency Severity Index (ESI) 1-5 scale,
--   where 1 = most critical, 5 = least urgent.
-- -----------------------------------------------------------------------------
CREATE TABLE triage (
    triage_id           VARCHAR(15)     NOT NULL,
    admission_id        VARCHAR(15)     NOT NULL,
    nurse_id            VARCHAR(15)     NOT NULL,
    triage_datetime     DATETIME        NOT NULL,
    bp_systolic         SMALLINT        NULL            COMMENT 'mmHg, typical range 70-200',
    bp_diastolic        SMALLINT        NULL            COMMENT 'mmHg, typical range 40-130',
    heart_rate          SMALLINT        NULL            COMMENT 'bpm, typical range 40-180',
    temperature         DECIMAL(4,1)    NULL            COMMENT 'Fahrenheit, typical range 95.0-105.0',
    respiratory_rate    TINYINT         NULL            COMMENT 'breaths/min, typical range 8-40',
    oxygen_saturation   TINYINT         NULL            COMMENT '%, typical range 85-100',
    height_cm           SMALLINT        NULL,
    weight_kg           DECIMAL(5,1)    NULL,
    pain_level          TINYINT         NULL            COMMENT '0-10 scale',
    chief_complaint     VARCHAR(200)    NULL,
    acuity_level        TINYINT         NULL            COMMENT 'ESI 1-5: 1=most critical',

    CONSTRAINT pk_triage            PRIMARY KEY (triage_id),
    CONSTRAINT fk_triage_admission  FOREIGN KEY (admission_id)
                                        REFERENCES admissions (admission_id)
                                        ON DELETE CASCADE
                                        ON UPDATE CASCADE,
    CONSTRAINT fk_triage_nurse      FOREIGN KEY (nurse_id)
                                        REFERENCES nurses (nurse_id)
                                        ON DELETE RESTRICT
                                        ON UPDATE CASCADE,
    CONSTRAINT chk_bp_systolic      CHECK (bp_systolic IS NULL
                                        OR (bp_systolic BETWEEN 60 AND 250)),
    CONSTRAINT chk_bp_diastolic     CHECK (bp_diastolic IS NULL
                                        OR (bp_diastolic BETWEEN 30 AND 150)),
    CONSTRAINT chk_heart_rate       CHECK (heart_rate IS NULL
                                        OR (heart_rate BETWEEN 20 AND 300)),
    CONSTRAINT chk_temperature      CHECK (temperature IS NULL
                                        OR (temperature BETWEEN 90.0 AND 110.0)),
    CONSTRAINT chk_resp_rate        CHECK (respiratory_rate IS NULL
                                        OR (respiratory_rate BETWEEN 4 AND 60)),
    CONSTRAINT chk_o2_sat           CHECK (oxygen_saturation IS NULL
                                        OR (oxygen_saturation BETWEEN 50 AND 100)),
    CONSTRAINT chk_pain             CHECK (pain_level IS NULL
                                        OR (pain_level BETWEEN 0 AND 10)),
    CONSTRAINT chk_acuity           CHECK (acuity_level IS NULL
                                        OR (acuity_level BETWEEN 1 AND 5))
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Patient vital signs at intake — one record per admission';

CREATE INDEX idx_triage_admission   ON triage (admission_id);


-- -----------------------------------------------------------------------------
-- diagnoses
-- ICD-10 coded diagnoses linked to an admission.
-- One admission can have multiple diagnoses (Primary, Secondary, etc).
-- icd10_code populated from icd10_diagnoses.py.
-- common_name column added in v2 via ALTER TABLE.
-- -----------------------------------------------------------------------------
CREATE TABLE diagnoses (
    diagnosis_id        VARCHAR(15)     NOT NULL,
    admission_id        VARCHAR(15)     NOT NULL,
    doctor_id           VARCHAR(15)     NOT NULL,
    icd10_code          VARCHAR(10)     NOT NULL        COMMENT 'ICD-10-CM format e.g. I21.9',
    diagnosis_date      DATE            NOT NULL,
    diagnosis_type      ENUM(
                            'Primary',
                            'Secondary',
                            'Tertiary',
                            'Complication'
                        )               NOT NULL,

    CONSTRAINT pk_diagnoses         PRIMARY KEY (diagnosis_id),
    CONSTRAINT fk_dx_admission      FOREIGN KEY (admission_id)
                                        REFERENCES admissions (admission_id)
                                        ON DELETE CASCADE
                                        ON UPDATE CASCADE,
    CONSTRAINT fk_dx_doctor         FOREIGN KEY (doctor_id)
                                        REFERENCES doctors (doctor_id)
                                        ON DELETE RESTRICT
                                        ON UPDATE CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'ICD-10 diagnoses per admission — v2 adds common_name column';

CREATE INDEX idx_dx_admission       ON diagnoses (admission_id);
CREATE INDEX idx_dx_icd10           ON diagnoses (icd10_code);
CREATE INDEX idx_dx_type            ON diagnoses (diagnosis_type);


-- -----------------------------------------------------------------------------
-- patient_procedures
-- Junction table: admissions × procedure catalog.
-- One admission can have multiple procedures.
-- Scheduled procedures (not yet performed) have status = 'Scheduled'.
-- -----------------------------------------------------------------------------
CREATE TABLE patient_procedures (
    patient_procedure_id    VARCHAR(15)     NOT NULL,
    admission_id            VARCHAR(15)     NOT NULL,
    procedure_id            VARCHAR(10)     NOT NULL,
    doctor_id               VARCHAR(15)     NOT NULL,
    procedure_date          DATETIME        NOT NULL,
    procedure_status        ENUM(
                                'Completed',
                                'Scheduled',
                                'Cancelled'
                            )               NOT NULL,
    notes                   VARCHAR(500)    NULL,

    CONSTRAINT pk_patient_procedures    PRIMARY KEY (patient_procedure_id),
    CONSTRAINT fk_pp_admission          FOREIGN KEY (admission_id)
                                            REFERENCES admissions (admission_id)
                                            ON DELETE CASCADE
                                            ON UPDATE CASCADE,
    CONSTRAINT fk_pp_procedure          FOREIGN KEY (procedure_id)
                                            REFERENCES procedures (procedure_id)
                                            ON DELETE RESTRICT
                                            ON UPDATE CASCADE,
    CONSTRAINT fk_pp_doctor             FOREIGN KEY (doctor_id)
                                            REFERENCES doctors (doctor_id)
                                            ON DELETE RESTRICT
                                            ON UPDATE CASCADE
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Procedures performed or scheduled per admission';

CREATE INDEX idx_pp_admission       ON patient_procedures (admission_id);
CREATE INDEX idx_pp_procedure       ON patient_procedures (procedure_id);
CREATE INDEX idx_pp_status          ON patient_procedures (procedure_status);


-- -----------------------------------------------------------------------------
-- medications
-- Prescriptions issued during an admission.
-- dosage and frequency use standard clinical notation:
--   dosage:    '500mg', '10mg/5mL', '0.5mcg'
--   frequency: 'QD' (once daily), 'BID', 'TID', 'QID', 'PRN' (as needed)
-- -----------------------------------------------------------------------------
CREATE TABLE medications (
    medication_id       VARCHAR(15)     NOT NULL,
    admission_id        VARCHAR(15)     NOT NULL,
    doctor_id           VARCHAR(15)     NOT NULL,
    drug_name           VARCHAR(100)    NOT NULL,
    dosage              VARCHAR(50)     NOT NULL,
    frequency           VARCHAR(50)     NOT NULL        COMMENT 'e.g. QD, BID, TID, PRN',
    start_date          DATE            NOT NULL,
    end_date            DATE            NULL,
    med_status          ENUM(
                            'Active',
                            'Discontinued',
                            'Completed'
                        )               NOT NULL,

    CONSTRAINT pk_medications       PRIMARY KEY (medication_id),
    CONSTRAINT fk_med_admission     FOREIGN KEY (admission_id)
                                        REFERENCES admissions (admission_id)
                                        ON DELETE CASCADE
                                        ON UPDATE CASCADE,
    CONSTRAINT fk_med_doctor        FOREIGN KEY (doctor_id)
                                        REFERENCES doctors (doctor_id)
                                        ON DELETE RESTRICT
                                        ON UPDATE CASCADE,
    CONSTRAINT chk_med_dates        CHECK (end_date IS NULL OR end_date >= start_date)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Prescriptions and medication orders per admission';

CREATE INDEX idx_med_admission      ON medications (admission_id);
CREATE INDEX idx_med_drug           ON medications (drug_name);


-- -----------------------------------------------------------------------------
-- medical_tests
-- Lab, imaging, and diagnostic tests ordered during an admission.
-- nurse_id is nullable — some tests are ordered by doctors without
--   direct nurse involvement (e.g. remote imaging reads).
-- result and result_date are nullable until the test is completed.
-- -----------------------------------------------------------------------------
CREATE TABLE medical_tests (
    test_id             VARCHAR(15)     NOT NULL,
    admission_id        VARCHAR(15)     NOT NULL,
    doctor_id           VARCHAR(15)     NOT NULL,
    nurse_id            VARCHAR(15)     NULL            COMMENT 'NULL if no nurse involvement',
    test_name           VARCHAR(100)    NOT NULL,
    test_category       ENUM(
                            'Blood Panel',
                            'Urinalysis',
                            'Imaging',
                            'Pathology',
                            'Cardiology',
                            'Microbiology',
                            'Neurology'
                        )               NOT NULL,
    test_date           DATETIME        NOT NULL,
    result              VARCHAR(200)    NULL,
    result_date         DATE            NULL,
    cost                DECIMAL(10,2)   NOT NULL,

    CONSTRAINT pk_medical_tests     PRIMARY KEY (test_id),
    CONSTRAINT fk_test_admission    FOREIGN KEY (admission_id)
                                        REFERENCES admissions (admission_id)
                                        ON DELETE CASCADE
                                        ON UPDATE CASCADE,
    CONSTRAINT fk_test_doctor       FOREIGN KEY (doctor_id)
                                        REFERENCES doctors (doctor_id)
                                        ON DELETE RESTRICT
                                        ON UPDATE CASCADE,
    CONSTRAINT fk_test_nurse        FOREIGN KEY (nurse_id)
                                        REFERENCES nurses (nurse_id)
                                        ON DELETE SET NULL
                                        ON UPDATE CASCADE,
    CONSTRAINT chk_test_cost        CHECK (cost >= 0),
    CONSTRAINT chk_result_date      CHECK (result_date IS NULL
                                        OR result_date >= DATE(test_date))
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Lab and diagnostic tests per admission';

CREATE INDEX idx_test_admission     ON medical_tests (admission_id);
CREATE INDEX idx_test_category      ON medical_tests (test_category);


-- -----------------------------------------------------------------------------
-- staff_shifts
-- Shift scheduling for doctors, nurses, and employees.
-- staff_id references doctors, nurses, or employees depending on staff_type.
-- This is a standard polymorphic reference pattern — staff_id cannot be a
--   hard FK because it points to three different tables.
-- Handle joins in SQL with a CASE on staff_type, or separate views per role.
-- -----------------------------------------------------------------------------
CREATE TABLE staff_shifts (
    shift_id            VARCHAR(15)     NOT NULL,
    staff_id            VARCHAR(15)     NOT NULL        COMMENT 'FK to doctors, nurses, or employees — see staff_type',
    staff_type          ENUM(
                            'Doctor',
                            'Nurse',
                            'Employee'
                        )               NOT NULL,
    department_id       VARCHAR(10)     NOT NULL,
    shift_date          DATE            NOT NULL,
    shift_type          ENUM(
                            'Morning',      -- 07:00–15:00
                            'Afternoon',    -- 15:00–23:00
                            'Night'         -- 23:00–07:00
                        )               NOT NULL,
    hours_worked        DECIMAL(4,1)    NOT NULL        DEFAULT 8.0,

    CONSTRAINT pk_staff_shifts      PRIMARY KEY (shift_id),
    CONSTRAINT fk_shift_department  FOREIGN KEY (department_id)
                                        REFERENCES departments (department_id)
                                        ON DELETE RESTRICT
                                        ON UPDATE CASCADE,
    CONSTRAINT chk_hours_worked     CHECK (hours_worked > 0 AND hours_worked <= 24)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Staff shift scheduling — polymorphic staff_id references doctors/nurses/employees';

CREATE INDEX idx_shift_staff        ON staff_shifts (staff_id, staff_type);
CREATE INDEX idx_shift_department   ON staff_shifts (department_id);
CREATE INDEX idx_shift_date         ON staff_shifts (shift_date);


-- =============================================================================
-- DOMAIN 4 — FINANCIAL
-- Depend on admissions, patients, payers, patient_procedures, medical_tests
-- Generate last
-- =============================================================================

-- -----------------------------------------------------------------------------
-- billing
-- One bill per admission (enforced by UNIQUE on admission_id).
-- total_amount should equal the sum of billing_line_items.total_cost —
--   enforce this in the Python generator rather than a trigger in v1.
-- patient_responsibility = total_amount - insurance_covered
-- -----------------------------------------------------------------------------
CREATE TABLE billing (
    bill_id                 VARCHAR(15)     NOT NULL,
    admission_id            VARCHAR(15)     NOT NULL,
    patient_id              VARCHAR(15)     NOT NULL,
    payer_id                VARCHAR(10)     NOT NULL,
    bill_date               DATE            NOT NULL,
    due_date                DATE            NULL,
    total_amount            DECIMAL(12,2)   NOT NULL,
    insurance_covered       DECIMAL(12,2)   NOT NULL    DEFAULT 0.00,
    patient_responsibility  DECIMAL(12,2)   NOT NULL    DEFAULT 0.00,
    payment_status          ENUM(
                                'Pending',
                                'Partial',
                                'Paid',
                                'Denied',
                                'Write-Off'
                            )               NOT NULL    DEFAULT 'Pending',
    payment_date            DATE            NULL,

    CONSTRAINT pk_billing               PRIMARY KEY (bill_id),
    CONSTRAINT uq_billing_admission     UNIQUE (admission_id),
    CONSTRAINT fk_bill_admission        FOREIGN KEY (admission_id)
                                            REFERENCES admissions (admission_id)
                                            ON DELETE RESTRICT
                                            ON UPDATE CASCADE,
    CONSTRAINT fk_bill_patient          FOREIGN KEY (patient_id)
                                            REFERENCES patients (patient_id)
                                            ON DELETE RESTRICT
                                            ON UPDATE CASCADE,
    CONSTRAINT fk_bill_payer            FOREIGN KEY (payer_id)
                                            REFERENCES payers (payer_id)
                                            ON DELETE RESTRICT
                                            ON UPDATE CASCADE,
    CONSTRAINT chk_total_amount         CHECK (total_amount >= 0),
    CONSTRAINT chk_insurance_covered    CHECK (insurance_covered >= 0),
    CONSTRAINT chk_patient_resp         CHECK (patient_responsibility >= 0),
    CONSTRAINT chk_payment_date         CHECK (payment_date IS NULL
                                            OR payment_date >= bill_date)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'One bill per admission — financial summary';

CREATE INDEX idx_billing_patient        ON billing (patient_id);
CREATE INDEX idx_billing_payer          ON billing (payer_id);
CREATE INDEX idx_billing_status         ON billing (payment_status);
CREATE INDEX idx_billing_dates          ON billing (bill_date, due_date);


-- -----------------------------------------------------------------------------
-- billing_line_items
-- Individual charges that roll up to a billing record.
-- item_type determines which reference FK is relevant:
--   Procedure  → patient_procedure_id populated
--   Lab        → test_id populated
--   Medication → both NULL (drugs billed by name via description)
--   Room       → both NULL (room charge by day)
--   Consultation → both NULL
-- covered_amount is the portion paid by the payer.
-- -----------------------------------------------------------------------------
CREATE TABLE billing_line_items (
    line_item_id            VARCHAR(15)     NOT NULL,
    bill_id                 VARCHAR(15)     NOT NULL,
    item_type               ENUM(
                                'Procedure',
                                'Medication',
                                'Room',
                                'Lab',
                                'Consultation'
                            )               NOT NULL,
    patient_procedure_id    VARCHAR(15)     NULL        COMMENT 'Populated for item_type = Procedure',
    test_id                 VARCHAR(15)     NULL        COMMENT 'Populated for item_type = Lab',
    description             VARCHAR(200)    NOT NULL,
    quantity                SMALLINT        NOT NULL    DEFAULT 1,
    unit_cost               DECIMAL(10,2)   NOT NULL,
    total_cost              DECIMAL(10,2)   NOT NULL,
    covered_amount          DECIMAL(10,2)   NOT NULL    DEFAULT 0.00,

    CONSTRAINT pk_line_items            PRIMARY KEY (line_item_id),
    CONSTRAINT fk_li_bill               FOREIGN KEY (bill_id)
                                            REFERENCES billing (bill_id)
                                            ON DELETE CASCADE
                                            ON UPDATE CASCADE,
    CONSTRAINT fk_li_procedure          FOREIGN KEY (patient_procedure_id)
                                            REFERENCES patient_procedures (patient_procedure_id)
                                            ON DELETE SET NULL
                                            ON UPDATE CASCADE,
    CONSTRAINT fk_li_test               FOREIGN KEY (test_id)
                                            REFERENCES medical_tests (test_id)
                                            ON DELETE SET NULL
                                            ON UPDATE CASCADE,
    CONSTRAINT chk_quantity             CHECK (quantity > 0),
    CONSTRAINT chk_unit_cost            CHECK (unit_cost >= 0),
    CONSTRAINT chk_total_cost           CHECK (total_cost >= 0),
    CONSTRAINT chk_covered_amount       CHECK (covered_amount >= 0),
    CONSTRAINT chk_total_vs_unit        CHECK (total_cost = unit_cost * quantity)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci
COMMENT = 'Individual billing line items per bill';

CREATE INDEX idx_li_bill            ON billing_line_items (bill_id);
CREATE INDEX idx_li_item_type       ON billing_line_items (item_type);


-- =============================================================================
-- RE-ENABLE FK CHECKS
-- =============================================================================
SET FOREIGN_KEY_CHECKS = 1;


-- =============================================================================
-- SUMMARY VIEW
-- Quick sanity check — run after loading data to verify table row counts
-- =============================================================================
CREATE OR REPLACE VIEW vw_table_summary AS
SELECT 'departments'        AS table_name, COUNT(*) AS row_count FROM departments       UNION ALL
SELECT 'payers',                           COUNT(*)              FROM payers             UNION ALL
SELECT 'procedures',                       COUNT(*)              FROM procedures         UNION ALL
SELECT 'patients',                         COUNT(*)              FROM patients           UNION ALL
SELECT 'doctors',                          COUNT(*)              FROM doctors            UNION ALL
SELECT 'nurses',                           COUNT(*)              FROM nurses             UNION ALL
SELECT 'employees',                        COUNT(*)              FROM employees          UNION ALL
SELECT 'rooms',                            COUNT(*)              FROM rooms              UNION ALL
SELECT 'admissions',                       COUNT(*)              FROM admissions         UNION ALL
SELECT 'triage',                           COUNT(*)              FROM triage             UNION ALL
SELECT 'diagnoses',                        COUNT(*)              FROM diagnoses          UNION ALL
SELECT 'patient_procedures',               COUNT(*)              FROM patient_procedures UNION ALL
SELECT 'medications',                      COUNT(*)              FROM medications        UNION ALL
SELECT 'medical_tests',                    COUNT(*)              FROM medical_tests      UNION ALL
SELECT 'staff_shifts',                     COUNT(*)              FROM staff_shifts       UNION ALL
SELECT 'billing',                          COUNT(*)              FROM billing            UNION ALL
SELECT 'billing_line_items',               COUNT(*)              FROM billing_line_items;
