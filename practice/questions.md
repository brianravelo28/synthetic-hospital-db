# SQL practice questions

Eighteen questions on the synthetic hospital database, from a single table up to window functions and data-quality checks. The answers are in `solutions.sql`, kept separate so they do not spoil the questions. Try each one first.

## Set up (no server needed)

```bash
pip install pandas
python practice/load_sqlite.py          # builds practice/hospital.db from the CSVs in app/data/
sqlite3 practice/hospital.db            # or open it in any SQLite client
```

The questions and solutions use SQLite's SQL. To practise on MySQL or MariaDB instead, see `mysql_notes.md`.

## The data in one minute

Seventeen related tables plus `icd10_lookup` (the diagnosis names). The full definitions are in [docs/SCHEMA.md](../docs/SCHEMA.md). The joins you will use most:

- `admissions` is the centre: `patient_id` → `patients`, `department_id` → `departments`, `admitting_doctor_id` → `doctors`, `room_id` → `rooms`.
- `diagnoses`, `patient_procedures`, `medications`, `medical_tests` and `billing` each point at `admission_id`. `patient_procedures.procedure_id` → `procedures`; `diagnoses.icd10_code` → `icd10_lookup`.
- `billing_line_items.bill_id` → `billing`.
- `staff_shifts.staff_id` is a doctor, a nurse or an employee, depending on `staff_type` (so there is no single foreign key).

A few things to know before you start:

- **All of it is synthetic.** The numbers describe how the data was generated, not real hospitals.
- **One year of admissions.** The data covers the last 12 months. The hospital starts empty at the beginning, so the first few weeks are not typical, and the first and last months of billing are partial.
- **Only some admissions happened.** `admission_status` is `Admitted` (still in hospital), `Discharged`, `Scheduled` (in the future) or `Cancelled`. `length_of_stay` exists only for discharged stays. Scheduled and cancelled admissions have no room, diagnoses or bill.
- **Dates are text** in ISO format (`2026-01-31 14:05:00`).
- `patients.age` is the age when the data was generated, not at the time of each admission.

## Warm-up: one table, filtering, aggregation

1. **How many admissions does each department have?** Show the busiest first. *(joins · `GROUP BY` · `COUNT`)*
2. **Which ten patients have the most admissions?** *(`ORDER BY` · `LIMIT`)*
3. **How many patients are in each age band, by sex?** Use the bands 0–17, 18–39, 40–64 and 65+. *(`CASE` · `GROUP BY`)*

## Joins and dates

4. **What is the average length of stay for each admission type?** Count only discharged stays. *(filtering · `AVG`)*
5. **Which department handles the most admissions per doctor?** Count every admission a doctor admitted, whatever its status; show doctors, admissions and admissions per doctor, only for departments with at least 10 doctors. *(joins · ratios · `HAVING`)* — *Hint: count each doctor's admissions first (a CTE), then join to the doctors, so a doctor with no admissions still counts.*
6. **What are the five most common diagnoses in each department?** Show the diagnosis names, not the codes. *(window functions: `ROW_NUMBER`)*
7. **How much was billed in each department each month?** Attribute a bill to the department of its admission, and the month to the bill date. *(multi-table join · date formatting · `SUM`)*
8. **What are the three most common procedures for each kind of primary diagnosis?** The kind is the first letter of the ICD-10 code (`I` circulatory, `J` respiratory, and so on). *(a join across four tables · ranking)* — *Look at what you get: do the procedures make sense for the diagnoses?*

## Harder: windows, CTEs, tricky joins

9. **For each department, what share of its discharged admissions began within 30 days of the same patient's previous discharge?** Look only at discharged admissions; a department's total is all of its discharged admissions (including each patient's first stay, which has no previous discharge); "within 30 days" means 30 days or fewer between the previous discharge and the new admission. *(`LAG` · date arithmetic · conditional counts)* — *Hint: `LAG(discharge_date)` over each patient's stays in date order gives the previous discharge on the same row.*
10. **What is the month-over-month change in billed revenue, with a running total?** *(`LAG` · cumulative `SUM`)* — *The first and last months are partial, so the biggest swings are at the edges.*
11. **For each day, how many patients are in a bed at midnight, and what percentage of the inpatient beds is that?** Run from the day of the first admission to the day of the last discharge. A stay counts on every midnight after it started and before it ended (a stay still under way has not ended). Inpatient beds are the rooms of type Standard, Private, ICU, NICU and Isolation (add up `bed_capacity`). *(a generated date series · interval overlap · joining on a range)* — *Hint: a stay covers a midnight if it started before it and ended after it (or has not ended). The count starts near zero because the hospital starts empty.*
12. **Which doctors are in the busiest tenth of their own department, by number of admissions?** Count every admission, include doctors with no admissions in the ranking, and keep doctors whose `PERCENT_RANK` within their department is at least 0.9 (doctors with equal counts share a rank, so a department can have fewer than a tenth of its doctors). *(`PERCENT_RANK` · CTEs)*
13. **How many hours did nurses work on night shifts, by nurse position?** *(the polymorphic join: `staff_shifts` joins to `nurses` only for rows where `staff_type = 'Nurse'`)*
14. **Which ten primary diagnoses have the highest average bill, and how does each compare with the median bill?** A bill's amount is `billing.total_amount`, and the median is over every row of `billing`. Ignore diagnoses with fewer than 20 bills. *(aggregation · a median computed with window functions · a scalar subquery or `CROSS JOIN`)*

## Data-quality checks: each should return zero rows

The pipeline that built this data runs checks like these. Each of the next four is a rule the data should satisfy, so a correct query returns **no rows**. (If one returned rows, either the query is wrong or you have found a bug.)

15. Find admissions whose discharge date is before their admission date.
16. Find diagnoses dated before the hire date of the doctor who made them.
17. Find diagnoses that contradict the patient's sex: pregnancy codes (`O…`) or breast cancer (`C50…`) on a male patient, prostate cancer (`C61`) on a female patient.
18. Find stays in a room that held more patients at once than the room has beds. *(a correlated subquery or a self-join on overlapping dates)* — *Hint: for each admission, count the admissions in the same room (including this one) that had started and not yet ended at the moment this one started. A stay that ends at the exact moment another one starts does not overlap it: the bed is free.*

---

After the questions, [`notebooks/03_sql_analysis.ipynb`](../notebooks/03_sql_analysis.ipynb) has more worked SQL examples, with the answers shown beside each question.
