# Methodology

Contents: [Terms](#terms) · [Data sources](#data-sources) · [Data and cleaning](#data-and-cleaning) · [Settings I chose](#settings-i-chose) · [The 59 checks](#the-59-checks) · [Rounds of fixes](#rounds-of-fixes) · [Occupancy](#occupancy) · [Reproducibility](#reproducibility) · [Deployment notes](#deployment-notes) · [Known limitations](#known-limitations)

A generator builds the 17-table database, a validator runs 59 consistency checks, and a repair step fixes what is left. In five rounds the same large hospital went from 99,532 violations (first generator) to 71 (current) before repair, and to 0 after it. The table and field layout follows published hospital-database designs; every number and proportion is a setting I chose; the checks are rules I wrote. The data is therefore internally consistent, not clinically realistic.

## Terms

| Term | Meaning |
|---|---|
| Admission | One row of `admissions`, whatever its status |
| Stay | An admission that happened: status `Admitted` (still in hospital) or `Discharged` |
| Scheduled, cancelled | `Scheduled` admissions are dated after the reference date; `Cancelled` ones have no stay. Some cancellations are drawn; some happen because no bed was free in time (see Occupancy). The CSVs do not say which |
| Needed a bed | A stay, or an admission cancelled for lack of a bed. The base of every occupancy rate |
| Census | Patients in an inpatient bed at midnight |
| Bed occupancy | Census divided by inpatient beds (Standard, Private, ICU, NICU, Isolation); averages leave out the first 45 days, because the hospital starts empty |
| Lower level of care | A patient placed in a less intensive room type than drawn, after waiting too long for the drawn type |
| Reference date | The date the data is "as of" (`AS_OF`, set with `HOSPITAL_AS_OF`); the shipped data uses 2026-10-13 12:00:00 |
| Before / after repair | Violations counted on the generator's own output, and after the repair step has run |
| Detect-only | A check with no repair; it reports only |
| Snapshot | One of three named points in the history: pre-patch (the first generator), post-round-one, current |
| Gender, sex at birth | Two fields on `patients`; sex-specific rules use sex at birth |
| ICD-10-CM, CPT | The US diagnosis coding system; the procedure coding system (copyrighted by the American Medical Association) |
| ESI | Emergency Severity Index, a 1 (most urgent) to 5 triage scale |
| Foreign key, `CHECK` | A column linking to another table's row; a constraint that rejects a row breaking a rule |

## Data sources

| Source | What | Version used |
|---|---|---|
| This repository's generator | 17 tables; names, addresses and dates from Faker, everything clinical and financial from weighted random draws | Faker 40.43.0; seeds fixed; reference date 2026-10-13 12:00:00 |
| ICD-10-CM (CDC/NCHS) | 66 real diagnosis codes in 13 categories, selected by hand, with hand-set weights | not versioned |
| CPT (AMA) | 30 real procedure code numbers with names written for this project; the AMA's descriptors are not reproduced | not versioned |
| Five hospital-database designs | the table and field layout | [CITATIONS.md](CITATIONS.md) |
| USCDI Version 2 (ONC) | the separate "Sex (assigned at birth)" and "Gender Identity" elements | July 2021 |

## Data and cleaning

**Measure.** Each of the 12,000 admissions is drawn as Scheduled (5%), Cancelled (5%) or Completed (90%); the dates then decide whether a completed one is `Discharged` or still `Admitted`. The allocator may later cancel a few completed ones for lack of a bed.

**Funnel.** Nothing is dropped from the generated data; the table shows where the 12,000 admissions end up.

| Step | Admissions |
|---|---|
| Drawn | 12,000 |
| Scheduled (after the reference date) | 592 |
| Drawn as cancelled | 564 |
| Needed a bed | 10,844 |
| Cancelled for lack of a bed | 51 |
| Placed (stays) | 10,793 |
| of which still admitted | 170 |
| of which discharged | 10,623 |

The 615 `Cancelled` rows in the CSV are the 564 drawn plus the 51. Nulls follow the status: `room_id` is empty for scheduled and cancelled admissions (1,207 rows), `discharge_date` and `length_of_stay` for every admission that has not ended, and `patients.email` for patients under 13. The repair step changes 71 rows at large size (2 at small, 17 at medium), all one rule: a patient's registration date is set to the admission date of a newborn. The counts come from `docs/validation_runs/` and `app/data/validation_report_occupancy.json`.

## Settings I chose

None of these comes from a study or a hospital's figures. Each is set in the file named.

| Setting | Value | File |
|---|---|---|
| Diagnosis weights | 2.5 to 9.5, common conditions higher | `data/icd10_diagnoses.py` |
| Age mix | newborn 1.5%, 1 to 17 13.5%, 18 to 39 20%, 40 to 64 30%, 65 and over 35% | `AGE_BANDS` |
| Gender | M 48%, F 48%, NB 4% | `PATIENT_GENDER_P` |
| Admission category | Scheduled 5%, Cancelled 5%, Completed 90% | `ADMISSION_CATEGORY_P` |
| Patient condition | Minimal 15%, Moderate 40%, Maximum 30%, Intensive 15% | `CONDITION_P` |
| Stay length | exponential, mean 5 days, capped at 45 | `MAX_STAY_DAYS` |
| Bill date | 0 to 90 days after discharge | `gen_billing` |
| Planned occupancy | Standard 60%, Private 58%, ICU 78%, NICU 75%, Isolation 55%; rooms sized 10% tighter (factor 1.10) so the large hospital lands near 65% | `shared_rules.py` |
| Bed wait | up to 168 hours (24 for a newborn) before a lower level of care | `MAX_BED_WAIT_HOURS` |
| Rooms | every department has at least one Standard and one ICU room | `data/occupancy.py` |
| Treatments | a coarse table from diagnosis family to procedures, drugs and tests; 20% from a general pool | `data/clinical_rules.py` |

## The 59 checks

Every check is a SQL query that counts violations. The descriptions match the Data Quality page.

| Group | Checks | What it catches | Repaired? |
|---|---|---|---|
| 1. Temporal | 10 | Dates out of order: discharge before admission, a diagnosis, procedure, test or triage record outside the stay, a test result before the test, a bill before discharge, a payment before the bill | Yes |
| 2. Age-based | 6 | Age that does not fit the context: a "newborn" admission for a patient older than 0, a child admitted to Geriatric, an adult admitted to Pediatrics, a newborn-only diagnosis code on an older patient | Yes |
| 3. Admission type | 8 | Scheduled admissions that already have triage, diagnoses, procedures, medications, tests, a bill or a room; an emergency admission with a low-urgency (ESI 4 to 5) triage | Yes |
| 4. Department consistency | 3 | An admitting doctor or a room from a different department than the admission; a room type that does not suit the patient's condition | Yes |
| 5. Diagnosis alignment | 3 | A pregnancy or breast-cancer code on a patient born male, a prostate-cancer code on a patient born female, a newborn-only code on an adult | Yes |
| 6. Financial | 5 | A bill total that is not the sum of its line items; a denied bill that still shows coverage; a written-off bill that still charges the patient; payment dates that do not match payment status | Yes |
| 7. Operational realism | 18 | More patients admitted than a department has beds, a room holding more patients than it has beds, a patient admitted while still in an earlier stay, a patient "admitted" for over 60 days, a billed procedure that belongs to another admission, a patient registered before birth, staff acting before their hire date | No (detect-only) |
| 8. Clinical coherence | 6 | A delivery on a patient who was not born female or is not of childbearing age, chemotherapy with no cancer diagnosis, insulin or metformin with no diabetes diagnosis, a Pap smear on a patient who was not born female or is under 21 | No (detect-only) |

Groups 1 to 6 were written alongside the generator, so a clean result there shows the generator follows its own rules. Groups 7 and 8 were written afterwards, without reference to the generator; once they found problems the generator was fixed until they passed. A clean result there means it passes the checks it was tuned against, not that the set is complete. They only report, because repairing one (a bill line that points at another patient's procedure) would mean inventing data.

**Can each check fail?** `tests/test_rules_fire.py` makes one violation per rule inside a transaction on a freshly generated small database, runs the check and rolls back. For 56 rules the count goes up. For 3 (`discharge_before_admission`, `result_before_test`, `payment_before_bill`) the table's own `CHECK` constraint rejects the row, so the violation cannot exist and the check is a second line of defence. A schema change that flips either outcome fails the test.

## Rounds of fixes

Each round has the same shape: problem, evidence, fix, result.

### Round 1: generator fixes

- **Problem.** The first generator produced rows that were individually plausible but collectively wrong: departments and admission types ignored age (a newborn in Cardiology), diagnoses had no sex or age filter, rooms ignored the patient's condition, bill dates ignored the discharge date.
- **Evidence.** `docs/validation_runs/legacy_generator_*.csv`: the first generator's output through the 51 checks that existed then, each size in its own process with the same seed. The generator itself is not in the repository.
- **Fix.** Age-bucketed department pools; a department-filtered diagnosis draw that excludes impossible codes; rooms filtered to the condition; bills dated 0 to 90 days after discharge; at least one doctor in every department.
- **Result.** At large size, before repair:

| Group | Pre-patch | Current |
|---|---|---|
| 1 · Temporal | 1,548 | 0 |
| 2 · Age-based | 4,250 | 71 |
| 3 · Admission type | 14,645 | 0 |
| 4 · Department | 5,119 | 0 |
| 5 · Diagnoses | 1,803 | 0 |
| 6 · Financial | 10,936 | 0 |
| 7 · Realism (detect-only) | 61,231 | 0 |
| **Total** | **99,532** | **71** |

Small: 6,177 to 2. Medium: 25,681 to 17. Groups 8 and the later checks did not exist, so they were not run on the pre-patch output. The improvement is measured for the patches together. The pre-patch output cannot be repaired: moving a bill's date forward to its discharge date violates `CHECK (payment_date >= bill_date)` (MariaDB error 4025).

### Round 2: realism checks

- **Problem.** The first six groups were nearly silent on the generator's output because it was built to satisfy them.
- **Evidence.** The three snapshots in the table below. The post-round-one snapshot (the large dataset after the round-one patches) had 19 violations in groups 1 to 6, all one rule (the newborn registration date), and 59,105 in the 16 realism checks written afterwards (`docs/validation_runs/baseline_before_fixes_large.csv`; 59,124 together). The `staff_hired_before_age_21` count (314) was computed from the old dataset's CSVs and added to the file by hand.
- **Fix.** Each cause was fixed in the generator (right-hand column).
- **Result.** All 16 checks pass.

| Snapshot | What it is | Violations, before repair |
|---|---|---|
| Pre-patch | The first generator | 99,532 on the 51 checks then |
| Post-round-one | After the round-one patches | 19 in groups 1 to 6; 59,105 in the 16 realism checks |
| Current | The present generator | 71 on all 59 checks |

The check set grew between snapshots, so the totals show direction, not a like-for-like rate.

| Check | Violations | What was wrong | Fix |
|---|---|---|---|
| `shift_before_hire_or_wrong_dept` | 18,241 | Shifts before a person's hire date, in departments they do not work in | Shifts start after hire, in the staff member's own department |
| `staff_event_before_hire` | 10,343 | Doctors and nurses acting before their hire date | Only staff already hired on the event's date are offered |
| `procedure_item_wrong_admission` | 8,232 | Billed procedures belonging to other admissions | Bills built from the admission's own records |
| `lab_item_wrong_admission` | 6,499 | Same, for lab tests | same |
| `cancelled_has_clinical_records` | 4,187 | Cancelled admissions with clinical records | Only admissions that happened get records |
| `procedure_or_lab_item_missing_link` | 2,665 | Line items with no procedure or test | same |
| `stale_admitted_over_60d` | 2,409 | Patients "currently admitted", one since 2020 | Status follows from dates |
| `bill_on_undischarged_admission` | 2,409 | Bills for patients still in hospital | Bills only for discharged admissions |
| `scheduled_in_past` | 1,820 | "Scheduled" admissions dated in the past | Scheduled admissions are future-dated |
| `pediatric_vitals_implausible` | 911 | Infants 140 to 200 cm and 45 to 150 kg at triage | Age-banded vitals |
| `bill_before_admission` | 555 | Bills dated before the admission began | Bills only after discharge |
| `staff_hired_before_age_21` | 314 | Doctors and nurses hired as children | Hire dates respect a minimum age |
| `admission_before_birth` | 298 | Admissions before the patient was born | Dates drawn from birth onward |
| `registered_before_birth` | 202 | Registered before being born | Registration on or after birth |
| `census_exceeds_bed_capacity` | 20 | Every department over its bed count | follows from the status fix |
| `registered_in_future` | 0 | none | guarded in repair |
| **Total** | **59,105** | | |

### Round 3: clinical coherence

- **Problem.** Procedures, medications and tests were drawn uniformly at random, independent of the diagnoses and the patient.
- **Evidence.** Six contradictions written as Group 8, run before touching the generator: 4,699 violations in the large dataset of the time (`app/data/validation_baseline_pre_coherence.csv`): `diabetes_drug_without_diabetes_dx` 1,643; `delivery_without_obstetric_dx` 879; `delivery_wrong_patient` 711; `cancer_treatment_without_cancer_dx` 680; `pap_smear_wrong_patient` 480; `adult_surgery_on_minor` 306.
- **Fix.** `data/clinical_rules.py` maps each ICD-10-CM code to a family and each family to plausible procedures, drugs and tests, with code-level overrides (appendicitis to appendectomy; type 1 diabetes gets insulin only) and a general-care pool for 20% of treatments. Eligibility filters use sex at birth and age at admission (deliveries need a patient born female of childbearing age; major adult surgery needs an adult; a Pap smear needs a patient born female and 21 or over).
- **Result.** Group 8 finds 0 before repair at all three sizes. It is written from CPT codes and drug names, not from the generator's mapping, and catches contradictions, not oddness; its diabetes rule is deliberately strict.

### Round 4: occupancy

- **Problem.** The earlier hospital was nearly empty: 12,000 admissions over 6.8 years gave an average census of 20.3 against 338 department beds and 560 rooms (6.0% occupancy), and nothing stopped two stays sharing a room or one patient being in two beds (the figures are in `docs/validation_runs/baseline_history.csv`, recomputed from commit 94b2de2).
- **Evidence.** In the one-year hospital, a random room with no capacity check would give 5,127 double-booked stays at large size, and 208 stays began while the patient was in an earlier stay (`app/data/validation_baseline_pre_occupancy.csv`); in the six-year data 37 did (0.34% of stays, same baseline file).
- **Fix.** Admissions cover the last 365 days. `data/occupancy.py` sizes each department's rooms from its expected patient-days, then places admissions in date order: a stay cannot start before the same patient's previous stay ends, a room never holds more patients than it has beds, and a patient with no suitable bed waits (up to a week; a newborn a day), then is placed at a lower level of care, and is cancelled only if no bed frees in time. Waiting moves the admission and discharge dates together. A department's `bed_capacity` is the sum of its inpatient rooms' beds.
- **Result.** `room_double_booked` and `patient_overlapping_admissions` (two new Group 7 checks) find 0. See Occupancy.

### Round 5: sex at birth and routing

- **Problem.** `patients.gender` (M, F or NB) served as identity and as the basis for medical rules. In the previous release, 54 of the 961 diagnoses of the 318 NB patients carried a male-only or female-only code, and 251 adult admissions to OB/GYN (228 stays) were for patients not recorded as F (`docs/validation_runs/baseline_history.csv`, recomputed from commit c2205fe).
- **Fix.** `patients.sex_at_birth` (M or F), separate from `gender`, as USCDI Version 2 lists separate sex and gender elements. Every sex-specific rule uses it. It equals gender for M and F patients and is drawn 50/50 for NB patients. Adults reach OB/GYN only if born female. Diagnosis sampling removes impossible codes from the department's pool and draws once; if a department has no allowed code it raises an error instead of falling back to another department's codes, and a test checks every department, sex and age band the router can produce (59 combinations). Repair uses the same sampler.
- **Result.** The sex rules find 0 before repair at all three sizes. Staff and patient rows changed in this round because the new draw moved the random stream (see Reproducibility).

## Occupancy

Recorded per size in `docs/validation_runs/<size>_occupancy.json`, written by the pipeline and recomputed from the shipped CSVs by `tests/test_run_summary.py` (large). Averages leave out the first 45 days.

| Size | Rooms | Inpatient beds | Average census | Average bed occupancy | Busiest day |
|---|---|---|---|---|---|
| Small | 47 | 62 | 9.2 | 14.8% | 27.4% |
| Medium | 75 | 84 | 37.3 | 44.4% | 69.0% |
| Large | 199 | 212 | 136.8 | 64.5% | 77.8% |

**Planned and realised, at large size.** The realised figures differ from the plan in both directions. Rooms come in whole units, every department needs a Standard and an ICU room, and each department's rooms are a separate pool, so a small pool can be full while the hospital is not. I have not separated how much each contributes.

| Room type | Planned | Realised | Beds |
|---|---|---|---|
| Standard | 60% | 62.2% | 82 |
| Private | 58% | 68.8% | 66 |
| ICU | 78% | 71.2% | 43 |
| NICU | 75% | 50.8% | 2 |
| Isolation | 55% | 46.0% | 19 |

**What keeping rooms within capacity cost.** Every rate is a share of the admissions that needed a bed (724 at small, 2,895 at medium, 10,844 at large).

| Size | Waited (mean hours) | Lower level of care | Moved after the patient's previous stay | Cancelled for lack of a bed |
|---|---|---|---|---|
| Small | 50 (6.9%; 59.7 h) | 15 (2.1%) | 13 (1.8%) | 0 |
| Medium | 668 (23.1%; 68.9 h) | 121 (4.2%) | 67 (2.3%) | 5 (0.17%) |
| Large | 2,444 (22.5%; 44.6 h) | 130 (1.2%) | 221 (2.0%) | 51 (0.47%) |

Some waiting is unavoidable at a realistic occupancy. Small and medium stay sparse because every department needs an ICU and a Standard room: a floor, not a target. The condition mix stays close to the drawn mix (Intensive 14.0% against 15%).

## Reproducibility

**Run order.** `data/hospital_db.sql` creates the schema; `src/run_pipeline.py --size <size>` generates, validates, repairs, validates again, writes the validation report, the occupancy summary and (for the shipped size) the CSVs and their checksums; `src/build_history_baselines.py` recomputes the history figures from earlier commits.

**Determinism.** Seeds are fixed and the whole pipeline reads one reference date (`AS_OF`), set with `HOSPITAL_AS_OF`; unpinned it is the wall clock. Faker's own `date_of_birth()` reads the clock, so staff birth dates are computed from `AS_OF`. Repair picks values from a hash of each row's id, not `RAND()`, and changes only rows that violate a rule. With the date pinned, two runs give identical tables and a different date gives different tables; running repair twice changes nothing. Re-running the unchanged code reproduced all 18 shipped CSVs byte for byte (checked 2026-11-16). The random state is not reset between runs inside one Python process, so reproducibility tests use separate processes.

**Data version.** `app/data/checksums.json` holds the SHA-256 of each of the 18 CSVs, taken with CRLF line endings read as LF so that Windows and Linux checkouts give the same value; a test checks them. A generator change that moves the random stream changes rows that follow it: the round-five change moved the stream before staff are generated, so the four staff files changed (every row), which the checksums make visible.

**Software.** Python 3.11 to 3.14 (CI). Dependencies are pinned exactly in `requirements.txt` and `app/requirements.txt`: SQLAlchemy 2.1.7, PyMySQL 1.2.3, Faker 40.43.0, NumPy 2.4.6, pandas 3.1.0, Streamlit 1.66.1, Plotly 7.1.0. NumPy 2.5 needs Python 3.12 or later and is not applied. The integration tests run on MariaDB 10.4 (end of life June 2024; what XAMPP ships) and 10.11.

**Tests.** `tests/` runs without a database except the integration tests, which regenerate the target database and run only when `HOSPITAL_DB_URL` is set.

- `test_generator_units.py`: age sampling, hire dates, no impossible diagnosis code for either sex at birth, every department, sex and age band the router produces has an allowed diagnosis, age-banded vitals, no wall-clock reads.
- `test_clinical_rules.py`: the diagnosis-to-treatment mapping (no deliveries for patients born male, chemotherapy without cancer or insulin without diabetes over seeded draws).
- `test_occupancy.py`: room planning and allocation (no room over capacity, no patient in two beds, waits only move an admission later, a newborn waits at most a day, every rate's base).
- `test_validator_and_app.py`: 59 unique rules, each with a dashboard description; chart table views; the census calculation.
- `test_run_summary.py`: the recorded occupancy summary recomputes from the shipped CSVs; census matches the dashboard; the checksums match; no room type exceeds its beds on any day.
- `test_practice.py`: every practice solution runs, the four data-quality solutions return no rows, the SQL census matches the dashboard's.
- `test_shipped_data.py`: pandas versions of the realism and clinical rules on the shipped CSVs.
- `test_pipeline_integration.py`: all 59 checks run; groups 3, 6 and 8 and the room and patient-overlap checks are clean before repair; the pinned date gives identical tables and a different date different tables; repair twice changes nothing; the run writes its occupancy summary and checksums.
- `test_rules_fire.py`: one injected violation per rule (see The 59 checks).
- `test_doc_figures.py`: every figure the README and this document quote is recomputed from the committed files; the test names the sentence that no longer matches.
- `.github/workflows/ci.yml`: the tests without a database on Python 3.11, 3.12, 3.13 and 3.14; the integration tests on Python 3.11, 3.13 and 3.14, each against MariaDB 10.4 and 10.11.

## Deployment notes

The dashboard runs on Streamlit Community Cloud (free tier): repository `brianravelo28/synthetic-hospital-db`, branch `main`, main file `app/app.py`, requirements `app/requirements.txt`. The app runs on Python 3.14, which is chosen in the app's settings on Streamlit Community Cloud, not in the repository (read there on 2026-11-16). CI covers Python 3.14 as well as 3.11 to 3.13, so the deployed version is tested; the dashboard pages are not rendered in CI. A push to `main` redeploys. The app sleeps when idle and took about two minutes to wake after a rebuild (observed 2026-11-03). It reads only the committed CSVs in `app/data/`, never a database. Memory use on the host is not measured. Layout and colour decisions are in [DASHBOARD.md](DASHBOARD.md).

## Known limitations

- **The checks measure consistency with rules I wrote**, not clinical realism, and Groups 7 and 8 were tuned against. The diagnosis-to-treatment mapping is coarse and hand-built; vitals ranges are plausible bands, not clinical references.
- **Numbers are chosen** (Settings I chose); findings describe this dataset, not hospitals.
- **Occupancy has side effects.** At large size, 22.5% of the admissions that needed a bed start when one frees, not at the drawn time, and 1.2% are placed at a lower level of care. Realised occupancy by room type differs from the plan. Small and medium are sparse.
- **Cancelled has two origins** in the CSVs (drawn, and for lack of a bed) and nothing marks which.
- **Staff are attributed hospital-wide**: diagnoses, procedures, medications and tests go to any already-hired doctor, not one from the admission's department.
- **`patients.age` is a snapshot** taken at generation; department routing uses it, while the treatment rules use age at admission.
- **Sex and gender are simplified.** Sex at birth equals gender for M and F patients and is drawn 50/50 for NB; no other combinations occur.
- **No live-database mode.** Re-run the pipeline and push the result to refresh the deployed app.
- **MariaDB 10.4 is past end of life;** MySQL 8 is untested.
