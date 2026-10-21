# Methodology

How the data is built, how it is checked, what each round of fixes found, and where it stops being realistic.

## Summary

- A generator builds the 17-table database, a validator runs **59 consistency checks**, and a repair step fixes what is left. The generator prevents most violations; at large size repair fixes only the newborn registration date.
- Four rounds of fixes, each measured before and after: generator fixes, independent realism checks, treatments that fit the diagnosis, and realistic occupancy.
- The first generator's data passed the original six check groups with 19 violations; the 16 independent checks written afterwards found 59,105.
- Everything is synthetic, and the checks test consistency with rules I wrote, not clinical realism. See [Known limitations](#known-limitations).

Terms: a *foreign key* links a column to another table's row; `CHECK` is a constraint that rejects a row breaking a rule; ICD-10 is the diagnosis coding system; CPT is the procedure coding system; ESI is the Emergency Severity Index, a 1 (most urgent) to 5 triage scale.

## The 59 checks

Every check is a SQL query that counts violations. They are grouped by what they catch. The descriptions match the Data Quality page of the dashboard.

| Group | Checks | What it catches | Repaired? |
|---|---|---|---|
| 1. Temporal | 10 | Dates out of order: discharge before admission, a diagnosis, procedure, test or triage record outside the stay, a test result before the test, a bill before discharge, a payment before the bill | Yes |
| 2. Age-based | 6 | Age that does not fit the context: a "newborn" admission for a patient older than 0, a child admitted to Geriatric, an adult admitted to Pediatrics, a newborn-only diagnosis code on an older patient | Yes |
| 3. Admission type | 8 | Scheduled (future) admissions that already have triage, diagnoses, procedures, medications, tests, a bill or a room; an emergency admission with a low-urgency (ESI 4–5) triage | Yes |
| 4. Department consistency | 3 | An admitting doctor or a room from a different department than the admission; a room type that does not suit the patient's condition (for example an "Intensive" patient in a standard room) | Yes |
| 5. Diagnosis alignment | 3 | A pregnancy or breast-cancer code on a male patient, a prostate-cancer code on a female patient, a newborn-only code on an adult | Yes |
| 6. Financial | 5 | A bill total that is not the sum of its line items; a denied bill that still shows coverage; a written-off bill that still charges the patient; payment dates that do not match payment status | Yes |
| 7. Operational realism | 18 | Things that look wrong in a join or on a dashboard: more patients admitted than a department has beds, a room holding more patients than it has beds, a patient admitted while still in an earlier stay, a patient "admitted" for over 60 days, a billed procedure that belongs to a different admission, a patient registered before they were born, staff recorded acting before their hire date | No (detect-only) |
| 8. Clinical coherence | 6 | Treatments that contradict the patient or diagnosis: a delivery on a patient who is not female or not of childbearing age, chemotherapy with no cancer diagnosis, insulin or metformin with no diabetes diagnosis, a Pap smear on a patient who is male or under 21 | No (detect-only) |

Groups 1 to 6 were written alongside the generator, so a clean result there shows the generator follows its own rules. Groups 7 and 8 were written afterwards and deliberately not designed around, to catch problems the generator was never built to avoid. They only report, because repairing them (for example a bill line that points at another patient's procedure) would mean inventing data.

## Round one: generator fixes

The first generator produced rows that were individually plausible but collectively wrong. Four causes were found by reading the generator against the validator's rules:

| Problem | Fix |
|---|---|
| Admission department and type ignored the patient's age (a newborn in Cardiology; the type "Newborn" on an 80-year-old) | Age-bucketed department pools; "Newborn" only for newborns |
| Diagnoses were sampled with no department, sex or age filter (pregnancy codes on male patients) | Department-filtered sample that rejects sex- and age-impossible codes, with a whole-catalog fallback (a resample loop alone still failed about 6.7% of the time for male patients in OB/GYN, whose diagnosis pool is almost all female-only; this is a unit test) |
| Room assignment ignored the patient's condition | Rooms filtered to the types allowed for the condition (since replaced by the allocator in round four) |
| Bill dates ignored the discharge date | Bills dated 0 to 90 days after discharge |

The archived pre-patch generator is not in this repository, so the comparison below can only be re-checked from the committed results files (`docs/validation_runs/legacy_generator_*.csv`), which came from running its output through the 51 checks that existed then, at each scale, each in its own process with the same seed. At large scale, before any repair:

| Group | Pre-patch generator | Current generator |
|---|---|---|
| 1 · Temporal | 1,548 | 0 |
| 2 · Age-based | 4,250 | 70 |
| 3 · Admission type | 14,645 | 0 |
| 4 · Department | 5,119 | 0 |
| 5 · Diagnoses | 1,803 | 0 |
| 6 · Financial | 10,936 | 0 |
| 7 · Realism (detect-only) | 61,231 | 0 |
| **Total** | **99,532** | **70** |

(Small: 6,177 → 2. Medium: 25,681 → 21. The pre-patch column covers the 51 checks that existed then; Group 8 and the new room check were written later and were not run against that output. The current column is the latest recorded run.) The round-one patches targeted groups 1, 2, 4 and 5, which together fell from 12,720 violations (1,548 + 4,250 + 5,119 + 1,803) to 70; groups 3 and 6 were untouched until round two. The improvement is measured for the patches together, not for each one separately.

**The pre-patch output cannot be repaired.** Run through the current `repair_all()`, it fails at every scale: moving a bill's date forward to its discharge date violates the table's own `CHECK (payment_date >= bill_date)` constraint (MariaDB error 4025 on `chk_payment_date`), because those bills had payment dates before the discharge. The current generator never produces the conflicting dates.

### Departments with no doctors

At small scale (25 doctors, 20 departments), random assignment left 10 departments, Pediatrics among them, with no doctor. Admissions routed there produced `doctor_dept_mismatch` violations that repair could not fix, because there was no doctor in the department to reassign to (the repair log read "Reassigned doctors for 0 admissions" against 294 violations). The generator now guarantees at least one doctor per department, the same guarantee rooms already had. This is the one round-one fix with its own before and after: 294 → 0.

## Round two: independent realism checks

Round one ended with a validator that reported almost nothing, as expected, because the generator had been built to satisfy its rules. Group 7 was added afterwards: each rule catches something that looks wrong on the dashboard or in a join. Run against the large dataset the earlier generator had produced (groups 1–6 reported **19** violations on it, a fixed baseline in `docs/validation_runs/baseline_before_fixes_large.csv`), the 16 realism checks that existed then found:

| Check | Violations | What was wrong | Fix in the generator |
|---|---|---|---|
| `shift_before_hire_or_wrong_dept` | 18,241 | Shifts before a person's hire date, in departments they do not work in | Shifts start after hire, in the staff member's own department |
| `staff_event_before_hire` | 10,343 | Doctors and nurses acting before their hire date | Only staff already hired on the event's date are offered |
| `procedure_item_wrong_admission` | 8,232 | Billed procedures belonging to other admissions | Bills built from the admission's own records |
| `lab_item_wrong_admission` | 6,499 | Same, for lab tests | same |
| `cancelled_has_clinical_records` | 4,187 | Cancelled admissions with diagnoses, procedures, medications, tests | Only admissions that happened get clinical records |
| `procedure_or_lab_item_missing_link` | 2,665 | Line items with no procedure or test (deleted by repair, foreign key set `NULL`) | same |
| `stale_admitted_over_60d` | 2,409 | Patients "currently admitted", one since 2020-01-01 | Status follows from dates: a stay that has not ended is `Admitted` |
| `bill_on_undischarged_admission` | 2,409 | Bills for patients still in the hospital | Bills only for discharged admissions |
| `scheduled_in_past` | 1,820 | "Scheduled" admissions dated in the past | Scheduled admissions are future-dated |
| `pediatric_vitals_implausible` | 911 | Infants 140–200 cm and 45–150 kg at triage | Age-banded vitals |
| `bill_before_admission` | 555 | Bills dated before the admission began | Bills only after discharge |
| `staff_hired_before_age_21` | 314 | Doctors and nurses hired as children | Hire dates respect a minimum age |
| `admission_before_birth` | 298 | Admissions before the patient was born | Admission dates drawn from birth onward; newborns admitted at birth |
| `registered_before_birth` | 202 | Registered before being born | Registration dates on or after birth |
| `census_exceeds_bed_capacity` | 20 | Every department over its bed count | follows from the status fix |
| `registered_in_future` | 0 | none | guarded in repair, since scheduled admissions are in the future |
| **Total** | **59,105** | | |

(`staff_hired_before_age_21` was added after the baseline run, so its 314 was computed from the old dataset's committed CSVs, not read from the live database. Including its 19 Group 2 violations, the whole baseline file totals 59,124.)

Billing is now generated from the admission's own room stay, completed procedures, tests and medications, so a bill's total is the sum of its line items and line items cannot point at another admission. Scheduled and cancelled admissions never receive clinical records. As a result, groups 3 and 6 have no violations before repair. A "Newborn" admission can occur once per patient; what remains before repair is each newborn's registration date, which cannot be known when patients are created (they are generated before admissions), so repair sets it.

## Round three: clinical coherence

Procedures, medications and tests had been drawn uniformly at random from their catalogs, independent of the diagnoses and the patient. Six clear-cut contradictions were written as Group 8 (`validate_clinical_coherence()`) and run against the large dataset of the time, before touching the generator:

| Check | Violations | What it caught |
|---|---|---|
| `diabetes_drug_without_diabetes_dx` | 1,643 | Insulin or metformin on an admission with no diabetes diagnosis |
| `delivery_without_obstetric_dx` | 879 | A delivery procedure with no obstetric diagnosis |
| `delivery_wrong_patient` | 711 | A delivery on a patient who is not female or not aged 12–55 (445 of 907 deliveries were on male patients) |
| `cancer_treatment_without_cancer_dx` | 680 | Chemotherapy or radiation with no cancer diagnosis (680 of the 839 such procedures) |
| `pap_smear_wrong_patient` | 480 | A Pap smear on a patient who is not female or is under 21 |
| `adult_surgery_on_minor` | 306 | Bypass surgery, hip or knee replacement or hip-fracture fixation on a patient under 18 |
| **Total** | **4,699** | |

The baseline is `app/data/validation_baseline_pre_coherence.csv`. `data/clinical_rules.py` maps each ICD-10 code to a family (cardiac, respiratory, diabetes, oncology, obstetric and so on) and each family to plausible procedures, drugs and tests, with code-level overrides where one code is far more specific (appendicitis leads to an appendectomy; type 1 diabetes gets insulin only). A fifth of treatments come from a general-care pool (acetaminophen, a metabolic panel, a ward round). Eligibility filters use the patient's sex and age at admission, from `birth_date`: deliveries need a female patient of childbearing age, major adult surgery needs an adult, a Pap smear needs a woman of 21 or over, and a few drugs are withheld from young children.

Group 8 is written separately from CPT codes and drug names, not from the generator's mapping, so it tests the output instead of repeating the generator's rules. It finds 0 violations before repair at all three sizes. The mapping is coarse and hand-built, not clinical guidance: Group 8 catches contradictions, not oddness. The diabetes rule is deliberately strict (hospitals do sometimes give insulin to patients without diabetes).

## Round four: occupancy

The hospital had been nearly empty: 12,000 admissions over about 6.7 years left roughly 20 inpatients on average against 338 beds and 560 rooms (about 6%). Nothing stopped two stays sharing a room or one patient being in two beds at once; the emptiness hid both.

- **One-year window.** Admissions cover the last 365 days (`ADMISSION_WINDOW_DAYS`), with the same admission counts per size (800, 3,200, 12,000). Staff and patient identities and birth dates are unchanged.
- **Rooms sized from load.** `data/occupancy.py` computes each department's expected patient-days from how patients are routed by age and the stay-length distribution, then sizes each room type for a planned occupancy (`OCCUPANCY_TARGET`: Standard 60%, Private 58%, ICU 78%, NICU 75%, Isolation 55%, applied 10% tighter because rounding up to whole rooms leaves the realised figure below plan). Every department has at least one Standard and one ICU room. OR, ER and Recovery rooms exist but never hold an admission and are not beds. A department's `bed_capacity` is the sum of its inpatient rooms' beds.
- **One bed per patient, none over capacity.** Admissions are placed in date order. A stay cannot start before the same patient's previous stay ends (it moves to that time; a later admission for a patient still in hospital is cancelled), and a room never holds more patients than it has beds. A patient with no suitable bed waits for one (up to a week, `MAX_BED_WAIT_HOURS`; a newborn up to a day), then is placed at a lower level of care, and is cancelled only if no bed frees in time. Waiting moves the admission and discharge dates together.
- **Two new Group 7 checks.** `room_double_booked`: with rooms assigned the old way (a random suitable room, no capacity check) in this one-year hospital it would find 5,127 double-booked stays at large size and 1,050 at medium. `patient_overlapping_admissions`: stays that begin while the patient is in an earlier one; random dates had produced 37 (0.34%) in the earlier six-year data and 208 (1.9%) in the one-year data. Both baselines are in `app/data/validation_baseline_pre_occupancy.csv`; both checks find 0.

Measured on the generated data, averaged over the days after a 45-day warm-up (the hospital starts empty):

| Size | Rooms | Inpatient beds | Average census | Average bed occupancy | Busiest day |
|---|---|---|---|---|---|
| Small | 47 | 62 | 9 | 15% | 31% |
| Medium | 75 | 84 | 37 | 44% | 57% |
| Large | 204 | 218 | 138 | 63% | 76% |

At large size, average occupancy is Standard 61%, Private 68%, ICU 68%, Isolation 47% (NICU has 2 beds), and the condition mix stays close to the drawn mix (Intensive 14.0% against 15%). Keeping rooms within capacity took, at large size, 2,168 admissions (20%) waiting for a bed (mean 44 hours), 120 (1.1%) placed at a lower level of care, 225 (2.1%) moved to after the same patient's previous stay and 19 (0.18%) cancelled; at medium, 587 (20%) waited, 90 (3.1%) were stepped down and 8 cancelled; at small, 58 (8%) waited and 12 (1.7%) were stepped down. Each department's rooms are a separate pool, and small pools are often full, so some waiting is unavoidable at a realistic occupancy. Small and medium stay sparse because every department needs an ICU and a Standard room: a floor, not a target.

**Census** is the number of patients in an inpatient bed at midnight; **bed occupancy** is census divided by inpatient beds (Standard, Private, ICU, NICU, Isolation). The dashboard and practice question 11 use these definitions.

## Results across scale

Each run: generate, validate before any repair, repair, validate again. "Before repair" is what the generator produces by itself. Per-run reports are in `docs/validation_runs/`.

| Scale | Admissions | Before repair | After repair | What remains before repair |
|---|---|---|---|---|
| Small | 800 | 2 | 0 | 2 newborn registration dates |
| Medium | 3,200 | 21 | 0 | 21 newborn registration dates |
| Large | 12,000 | 70 | 0 | 70 newborn registration dates |

The newborn registration date is the only thing repair changes at any size. (When rooms were assigned at random, a department with no room suited to a patient's condition left a few `condition_room_mismatch` violations at small and medium scale; the room allocator removed that case.)

## Pipeline, dashboard and reproducibility

- `src/run_pipeline.py` runs generate → validate → repair → validate → export in one command and writes `app/data/validation_report.csv` (per-check before and after), a small metadata file and a per-scale summary the dashboard reads. `src/export_to_csv.py` exports the repaired database to `app/data/`, so the dashboard needs no live database and works the same locally and on Streamlit Community Cloud.
- The dashboard's **Data Quality** page presents the validation results; **Admissions & Census** includes the occupancy measures. Layout and colour decisions are in [DASHBOARD.md](DASHBOARD.md).
- **Reproducibility.** Seeds are fixed, and the whole pipeline reads one reference date (`AS_OF` in `data/shared_rules.py`), set with `HOSPITAL_AS_OF`; unpinned it is the wall clock, so counts shift slightly between runs. Faker's own `date_of_birth()` reads the system clock, so the generator computes staff birth dates from `AS_OF` instead. Repair picks values from a hash of each row's id (no `RAND()`) and changes only rows that violate a rule. With the date pinned, two runs give identical tables and a different date gives different tables; running repair a second time changes nothing. The integration tests check all three.

## Tests

- `test_generator_units.py`: pure logic: age sampling, hire dates, nobody acting before being hired, no impossible diagnosis codes, age-banded vitals, constants shared by generator and validator, no wall-clock reads.
- `test_clinical_rules.py`: the diagnosis-to-treatment mapping (everything it names exists; no deliveries for men, chemotherapy without cancer or insulin without diabetes over hundreds of seeded draws).
- `test_occupancy.py`: room planning, and allocation (no room over capacity, no patient in two beds, waits only move an admission later, step-down after a long wait, a newborn waits at most a day).
- `test_validator_and_app.py`: the rule set (59 unique rules, each with a dashboard description), the chart table views and the census calculation.
- `test_practice.py`: every practice solution runs, the four data-quality solutions return no rows, and the SQL census matches the dashboard's.
- `test_shipped_data.py`: pandas versions of the realism rules run against the CSVs in `app/data/`, so a regression is caught without a database. When first written, 8 of these tests failed against the pre-fix CSVs from git history.
- `test_pipeline_integration.py`: the whole pipeline against a real database. All 59 checks run; groups 3, 6 and 8 and the room and patient-overlap checks have no violations before repair; the same pinned date gives identical tables and a different date different tables; repair run twice changes nothing; the room check fires when two stays are forced into one bed. It regenerates the target database, so it runs only when `HOSPITAL_DB_URL` is set.
- `.github/workflows/ci.yml` runs the tests that need no database on Python 3.11, and the integration tests against a MariaDB 10.4 container.

## Known limitations

- **The checks measure consistency with rules I wrote**, not clinical realism. The diagnosis-to-treatment mapping is coarse and hand-built; Group 8 catches contradictions, not oddness. Age follows a hand-set curve (`AGE_BANDS`), and vitals ranges are plausible bands, not clinical references.
- **Diagnosis weights are hand-assigned judgement** (2.5 to 9.5, common conditions higher), not taken from CMS/HCUP or any study. The catalog is 66 ICD-10 codes in 13 categories.
- **Occupancy has side effects.** Keeping rooms within capacity means about 1 in 5 admissions starts when a bed frees, not at the drawn time, and a small share of patients are recorded at a lower level of care than drawn. Small and medium sizes are sparse (15% and 44% bed occupancy).
- **Groups 7 and 8 have no repair**, by design; they only report.
- **Staff are attributed hospital-wide**: diagnoses, procedures, medications and tests go to any already-hired doctor, not one from the admission's department.
- **`patients.age` is a snapshot** taken at generation; department routing uses it, while Group 8 and the treatment rules use age at admission.
- **Diagnosis sampling** uses a bounded resample with a whole-catalog fallback; filtering the pool once and drawing once would be simpler and could not fail silently.
- **No live-database mode.** The dashboard reads only the CSVs; re-run the pipeline and push the result to refresh the deployed app.
- **Developed on MariaDB 10.4.** MySQL 8 is untested; CI covers Python 3.11 and MariaDB 10.4 only.
