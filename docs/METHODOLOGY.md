# Methodology

## Starting point: a stale diagnosis

The project came with a hand-written problem writeup blaming the generate → repair loop on four things: date windows outside the admission period, age/department mismatches, invalid diagnosis codes, and doctor/department misalignment. Before writing any patch, each claim was checked against the actual generator code (`hospital_generator.py`) rather than taken on faith — and two of the four turned out to already be fixed:

- **Date windows** (diagnosis/procedure/medication/test/triage dates within the admission window) — already correctly constrained via `date_within_admission()` / `datetime_within_admission()`.
- **Doctor and room matched to admission department** — already correctly built from `dept_doctor_map` / `dept_room_map` lookups in `gen_admissions()`.

Patching things that weren't broken would have wasted the "preventive over reactive" budget on the wrong targets. The actual violation drivers were found by reading the rest of the generator against `validate_repair.py`'s rule set line by line.

## What was actually broken

**1. Admission department and type were age-blind.** `gen_admissions()` picked `department_id` and `admission_type` uniformly at random, with no reference to the patient's age. A newborn could land in Cardiology; `admission_type = 'Newborn'` could be assigned to an 80-year-old. This was the single largest driver of Group 2 (age-based) violations.

*Fix:* age-bucketed pools (`NEWBORN_DEPT_POOL`, `PEDIATRIC_DEPT_POOL`, an adult pool excluding Pediatrics) and admission-type sampling that excludes `'Newborn'` outright for non-newborn patients, with probabilities renormalized over the remaining types.

**2. `sample_diagnosis()` was called with no filters at all.** `gen_diagnoses()` sampled from the full 66-code ICD-10 list, department and gender/age unfiltered — routinely producing e.g. pregnancy-only codes (`O80`, `O34.21`, ...) for male patients.

*Fix:* `_sample_valid_diagnosis()` samples department-filtered first, then rejects gender/age-impossible codes with a bounded resample. Testing this in isolation found the resample loop alone still left a **~6.7% residual failure rate** for male patients admitted to OB/GYN — that department's diagnosis pool is almost entirely female-only codes, so 10 attempts wasn't always enough. Added a full-list (unfiltered-by-department) fallback for that case; verified 0/5,000 residual violations across three test scenarios (male/OB-GYN, female/Urology, pediatric/newborn-code exclusion) before shipping.

**3. Room assignment ignored `patient_condition` entirely.** A patient marked `Intensive` could be assigned any room in the department, ICU or not.

*Fix:* room candidates are now filtered to the room types allowed for that condition (mirroring `CONDITION_ROOM_MAP` in `validate_repair.py`), falling back to any in-department room only when no condition-appropriate room exists — a real resource-scarcity case, not a bug, and left for the repair pass to handle by downgrading the recorded condition.

**4. `gen_billing()`'s `bill_date` ignored `discharge_date`.** It was sampled independently over a 3-year window, so most bills predated the admission's actual discharge.

*Fix:* `bill_date` is now anchored to `discharge_date` (± up to 90 days) when one exists.

## A fifth bug, found by testing at small scale

Testing the patched generator with `main('small')` (25 doctors, 20 departments) surfaced something none of the four items above explained: `doctor_dept_mismatch` violations that **the repair pipeline could not fix at all** — `repair_department()` logged "Reassigned doctors for 0 admissions" every time, despite hundreds of violations.

Root cause: `gen_doctors()` assigns each doctor's department via `random.choice(SPECIALTY_TO_DEPARTMENT[specialty])`, with no minimum-per-department guarantee. At 25 doctors across 20 departments, **10 departments — including Pediatrics — ended up with zero doctors.** Any admission routed there produces a mismatch with no doctor in that department to reassign to. `gen_rooms()` already had exactly this guarantee (a department with no room gets one appended after the main loop); `gen_doctors()` never got the equivalent treatment.

*Fix:* added the same guaranteed-one-per-department pattern to `gen_doctors()`, mapping each empty department back to a plausible specialty via the reverse of `SPECIALTY_TO_DEPARTMENT`. This is very plausibly the real root cause of the original "regenerate → repair → still broken" complaint, since it made an entire violation category permanently unrepairable regardless of how many times the loop ran.

## Results across scale

Each run: generate with the patched generator, run `validate_all()` before any repair, run `repair_all()`, run `validate_all()` again.

| Scale | Admissions | Before repair | After repair | Eliminated |
|---|---|---|---|---|
| Small | 800 | 1,503 | 54 | 96.4% |
| Medium | 3,200 | 6,299 | 35 | 99.4% |
| Large | 12,000 | 25,720 | 22 | 99.9% |

One repair pass, every time — no regenerate loop needed at any scale.

Residual violations at every scale are two disclosed, structural edge cases, not regressions:
- **`condition_room_mismatch`** — only occurs when a department genuinely has no room of the condition-appropriate type available (worse at `small` scale, where the room pool is thinnest); repair correctly downgrades the recorded condition to match what's available rather than fabricate a room.
- **`newborn_wrong_registered_date`** — occurs when the same age-0 patient is independently selected for two different `Newborn`-type admissions with different dates; a patient has one `registered_date` and can satisfy at most one of them. Rare (22 of 12,000 admissions at large scale).

## Downstream pipeline

- `src/export_to_csv.py` exports the repaired database to `app/data/` so the dashboard (`app/`) never needs a live database connection — it works identically locally and once deployed to Streamlit Community Cloud, which can't reach a local MySQL instance.
- The dashboard's color system (`app/utils.py`) assigns colors by category identity, not chart-local rank or hue-cycling, and separates true evaluative "status" colors (e.g. payment status, discharge disposition) from plain categorical identity and from ordinal severity scales (`patient_condition`, test result severity) — see the module for the specific mappings.

## Known limitations

- **No live-DB mode** — the dashboard is CSV-only by design (see above); re-run `src/export_to_csv.py` after any regeneration to refresh it.
- **`validate_repair.py`'s Financial group (billing reconciliation) was left as pure repair, not prevented at generation** — `gen_billing_line_items()` still samples `total_amount` independent of the line items that get generated for it; reconciliation happens entirely in `repair_financial()`. This wasn't in scope for this pass since it's already fully cleaned by the existing repair step and isn't a source of unrepairable violations like the doctor-desert bug was.
- **The synthetic ICD-10 catalog is 66 codes across 13 categories** — enough for realistic-looking department/gender/age-consistent diagnosis distributions, not real clinical epidemiology.
