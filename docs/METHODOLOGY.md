# Methodology

## Starting point: a stale diagnosis

The project came with a hand-written problem writeup blaming the generate → repair loop on four things: date windows outside the admission period, age/department mismatches, invalid diagnosis codes, and doctor/department misalignment. Before writing any patch, each claim was checked against the actual generator code (`hospital_generator.py`) rather than taken on faith — and two of the four turned out to already be fixed:

- **Date windows** (diagnosis/procedure/medication/test/triage dates within the admission window) — already correctly constrained via `date_within_admission()` / `datetime_within_admission()`.
- **Doctor and room matched to admission department** — already correctly built from department lookups in `gen_admissions()`.

Patching things that weren't broken would have wasted the "preventive over reactive" budget on the wrong targets. The actual violation drivers were found by reading the rest of the generator against `validate_repair.py`'s rule set line by line.

## Round one: what was actually broken

**1. Admission department and type were age-blind.** `gen_admissions()` picked `department_id` and `admission_type` uniformly at random, with no reference to the patient's age. A newborn could land in Cardiology; `admission_type = 'Newborn'` could be assigned to an 80-year-old.

*Fix:* age-bucketed pools (`NEWBORN_DEPT_POOL`, `PEDIATRIC_DEPT_POOL`, an adult pool excluding Pediatrics) and admission-type sampling that excludes `'Newborn'` outright for non-newborn patients.

**2. `sample_diagnosis()` was called with no filters at all.** `gen_diagnoses()` sampled from the full 66-code ICD-10 list, department and gender/age unfiltered — routinely producing e.g. pregnancy-only codes (`O80`, `O34.21`, ...) for male patients.

*Fix:* `_sample_valid_diagnosis()` samples department-filtered first, then rejects gender/age-impossible codes with a bounded resample. Testing this in isolation found the resample loop alone still left a **~6.7% residual failure rate** for male patients admitted to OB/GYN — that department's diagnosis pool is almost entirely female-only codes, so 10 attempts wasn't always enough. Added a full-list fallback; verified 0/5,000 residual violations across three scenarios before shipping (and the same property is now a unit test). A cleaner design would filter the pool to allowed codes once and draw a single weighted sample — no retry loop to fail silently.

**3. Room assignment ignored `patient_condition`.** *Fix:* room candidates are filtered to the room types allowed for that condition (`CONDITION_ROOM_MAP`), falling back to any in-department room only when none exists.

**4. `gen_billing()`'s `bill_date` ignored `discharge_date`.** *Fix:* anchored to `discharge_date` (+0–90 days).

Items 1–4 were found by reading code and reasoning about what the validator would catch. **They were never measured against a baseline run of the old generator**, so this document makes no claim about how much each one helped.

### A fifth bug, found by testing at small scale

Testing the patched generator with `main('small')` (25 doctors, 20 departments) surfaced something none of the four items above explained: `doctor_dept_mismatch` violations that **the repair pipeline could not fix at all** — `repair_department()` logged "Reassigned doctors for 0 admissions" every time, despite hundreds of violations.

Root cause: `gen_doctors()` assigns each doctor's department via `random.choice(SPECIALTY_TO_DEPARTMENT[specialty])`, with no minimum-per-department guarantee. At 25 doctors across 20 departments, **10 departments — including Pediatrics — ended up with zero doctors.** Any admission routed there produces a mismatch with no doctor in that department to reassign to. `gen_rooms()` already had exactly this guarantee; `gen_doctors()` never got the equivalent treatment.

*Fix:* the same guaranteed-one-per-department pattern in `gen_doctors()`. This is the one fix with a measured before/after: 294 → 0 `doctor_dept_mismatch` violations at small scale. It is also very plausibly the real root cause of the original "regenerate → repair → still broken" complaint, since it made a whole violation category permanently unrepairable no matter how many times the loop ran.

## Second round: independent checks

Round one ended with a validator that reported almost nothing — which is exactly what you'd expect, because **the generator had been built to satisfy the validator's own rules.** Groups 1–6 were written alongside the generator and the constants are copied between them. "Zero violations" there means "consistent with rules I already knew about".

So Group 7 (16 checks, `validate_realism()` in `src/validate_repair.py`) was added *afterwards* and deliberately not designed around: each rule catches something that looks wrong on the dashboard or in a join. It is **detect-only** — there is no repair, because fixing e.g. a bill line that points at another patient's procedure would mean fabricating data.

Run against the large dataset the generator had produced *before* these fixes (groups 1–6 reported **19** violations on it):

| Check | Pre-fix violations | What was wrong | Fix in the generator |
|---|---|---|---|
| `shift_before_hire_or_wrong_dept` | 18,241 | Shifts before a person's hire date, in departments they don't work in | Shifts start after hire, in the staff member's own department |
| `staff_event_before_hire` | 10,343 | Doctors/nurses acting before their hire date | `StaffPool` only offers staff already hired on the event's date |
| `procedure_item_wrong_admission` | 8,232 | Billed procedures belonging to other admissions | Bills built bottom-up from the admission's own records |
| `lab_item_wrong_admission` | 6,499 | Same, for lab tests | same |
| `cancelled_has_clinical_records` | 4,187 | Cancelled admissions with diagnoses, procedures, medications, tests | Only admissions that happened get clinical records |
| `procedure_or_lab_item_missing_link` | 2,665 | Line items with no procedure/test (deleted by repair, FK set `NULL`) | same |
| `stale_admitted_over_60d` | 2,409 | Patients "currently admitted", one since 2020-01-01 | Status follows from dates: a stay that hasn't ended yet is `Admitted` |
| `bill_on_undischarged_admission` | 2,409 | Bills for patients still in the hospital | Bills only for discharged admissions |
| `scheduled_in_past` | 1,820 | "Scheduled" admissions dated in the past | Scheduled admissions are future-dated |
| `pediatric_vitals_implausible` | 911 | Infants 140–200 cm / 45–150 kg at triage | Age-banded vitals |
| `bill_before_admission` | 555 | Bills dated before the admission began | Bills only after discharge |
| `staff_hired_before_age_21` | 314 | Doctors/nurses hired as children | Hire dates respect a minimum age |
| `admission_before_birth` | 298 | Admissions before the patient was born | Admission dates drawn from birth onward; newborns admitted at birth |
| `registered_before_birth` | 202 | Registered before being born | Registration dates ≥ birth (generator and repair) |
| `census_exceeds_bed_capacity` | 20 | Every department over its bed count | (follows from the status fix) |
| `registered_in_future` | 0 | — | (guarded in repair, since scheduled admissions are now in the future) |
| **Total** | **59,105** | | |

(`staff_hired_before_age_21` was added after the baseline run, so its 314 was computed from the old dataset's committed CSVs rather than read from the live database. The baseline file is `docs/validation_runs/baseline_before_fixes_large.csv`.)

Several of these — admissions before birth, staff hired as children, doctors acting before being hired — were not on any list before the independent checks were written; they were found by asking "what else would be impossible?" rather than "what did the generator already know about?".

Two side effects worth knowing:

- **Groups 3 (admission type) and 6 (financial) are now prevented, not repaired.** Previously ~99.7% of the "before repair" count was those two groups — `Scheduled` admissions that still had clinical rows, and bill totals that never matched their line items — which repair cleared by deleting rows and recomputing. Billing is now generated bottom-up (the total *is* the sum of its line items), and scheduled/cancelled admissions are never given clinical records.
- **`Newborn` admissions can only occur once per patient**, which removed most of the old "two newborn admissions on different dates" edge case. What remains before repair is patients' `registered_date`, which can't be known when patients are created (they're generated before admissions); repair sets it.

## Results across scale

Each run: generate, `validate_all()` before any repair, `repair_all()`, `validate_all()` again. "Before repair" is what the generator produced by itself. Per-run reports are in `docs/validation_runs/`; the dashboard's Data Quality page shows them.

| Scale | Admissions | Before repair | After repair | What remains before / after |
|---|---|---|---|---|
| Small | 800 | 183 | 61 | 180 room-scarcity + 3 newborn registration dates / room-scarcity only |
| Medium | 3,200 | 79 | 37 | 64 + 15 / room-scarcity only |
| Large | 12,000 | 58 | 0 | 58 newborn registration dates / nothing |

**Retraction.** Earlier versions of this document and the README reported "25,720 → 22" at large scale and "99.9% eliminated". That was real arithmetic but misleading: it credited the generator for what repair was doing, and the groups the generator patches targeted accounted for only 84 of those violations. The table above is the honest version — and it is better, because the generator now prevents most of what repair used to clear.

The one residual that matters is **`condition_room_mismatch`**: it occurs when a department genuinely has no room of the type a patient's condition calls for (worst at small scale, where the room pool is thinnest). Repair downgrades the recorded condition rather than fabricate a room.

Counts shift by a few between regenerations (e.g. 1,503 vs 1,504 in two otherwise identical small runs): the seed fixes Python's random stream, but wall-clock dates and the repair step's SQL `RAND()` still vary.

## Pipeline and dashboard

- `src/run_pipeline.py` runs everything in one command — generate → validate → repair → validate → export — and writes `app/data/validation_report.csv` (per-check before/after), a small metadata file, and a per-scale summary the dashboard reads.
- `src/export_to_csv.py` exports the repaired database to `app/data/` so the dashboard never needs a live database connection — it works identically locally and on Streamlit Community Cloud (live at [synthetic-hospital-db.streamlit.app](https://synthetic-hospital-db.streamlit.app/)), which can't reach a local database.
- The dashboard's **Data Quality** page presents the validation results: violations by group before vs. after repair, results at each scale, what the independent checks found in the pre-fix data, and every rule with a plain-language description.
- Colors (`app/utils.py`) are assigned by category identity, not chart-local rank, and separate evaluative "status" colors from plain categorical identity and from ordinal severity scales. Layout conventions: a 13px minimum font, long chart labels wrapped to at most two lines by `wrap_label()`, KPI stat-tile cards via `render_kpi_row()` in the same position on every page (Admissions & Census reserves the slot above its filters and fills it once they're applied), and a drag-to-zoom hint under every zoomable chart via `plot()`.

## Tests

- `tests/test_generator_units.py` — pure logic: age sampling, hire dates, `StaffPool` (nobody acts before being hired), diagnosis sampling never returning impossible codes, age-banded vitals, and that the constants copied between the generator and validator stay identical.
- `tests/test_validator_and_app.py` — the rule set (51 unique rules, each with a dashboard description) and dashboard helpers.
- `tests/test_shipped_data.py` — pandas re-implementations of the realism rules, run against the CSVs actually shipped in `app/data/`, so a regression is caught without a database. Run against the *pre-fix* CSVs from git history, 8 of its tests fail — i.e. they do detect the original problems.
- `tests/test_pipeline_integration.py` — the whole pipeline against a real database; asserts all 51 checks run, that groups 3 and 6 have zero violations *before* repair, and that only room scarcity remains after. Runs only when `HOSPITAL_DB_URL` is set, because it regenerates the target database.
- `.github/workflows/ci.yml` runs the first three on Python 3.11 and the fourth against a MariaDB 10.4 service container. Both jobs passed on their first run.

## Known limitations

- **The checks measure consistency with rules the author wrote**, not clinical realism. Medications, procedures and diagnoses are drawn independently of each other (insulin without a diabetes diagnosis, adult doses for infants). Age follows a hand-set curve (`AGE_BANDS`), and vitals ranges are plausible bands, not clinical references.
- **The hospital is mostly empty.** 12,000 admissions across ~6.7 years is ~5 a day with a mean stay of ~5 days, so the true census is a few dozen patients against 560 rooms. Admission *volume* was kept at the original sizes rather than inventing a denser calendar.
- **Group 7 has no repair**, by design; it only reports.
- **No live-DB mode** — the dashboard is CSV-only by design; re-run the pipeline after any regeneration and push the result to refresh the deployed app.
- **Patient SSN/phone/email/address columns are kept in the CSVs** as Faker-generated placeholders; the dashboard doesn't read them.
- **Staff-to-department rules are strict only where checked**: diagnoses, procedures, medications and tests are attributed to any already-hired doctor in the hospital, not the admission's department.
- **Developed on MariaDB 10.4 (XAMPP)**; MySQL 8 and other Python versions are untested outside CI.
- **The synthetic ICD-10 catalog is 66 codes across 13 categories** — enough for realistic-looking department/gender/age-consistent diagnosis distributions, not real clinical epidemiology.
