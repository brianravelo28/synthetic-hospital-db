-- Solutions to practice/questions.md, written for SQLite (see mysql_notes.md for MySQL/MariaDB).
-- Try the question first; this file spoils the answers.
-- Each solution starts at a "-- Q<number>" line and ends at the next one.

-- Q1: Admissions per department
SELECT d.dep_name AS department, COUNT(*) AS admissions
FROM admissions a
JOIN departments d USING (department_id)
GROUP BY d.dep_name
ORDER BY admissions DESC, department;

-- Q2: Patients with the most admissions
SELECT patient_id, COUNT(*) AS admissions
FROM admissions
GROUP BY patient_id
ORDER BY admissions DESC, patient_id
LIMIT 10;

-- Q3: Patients by age band and sex
SELECT CASE WHEN age <= 17 THEN '0-17'
            WHEN age <= 39 THEN '18-39'
            WHEN age <= 64 THEN '40-64'
            ELSE '65+' END AS age_band,
       gender,
       COUNT(*) AS patients
FROM patients
GROUP BY age_band, gender
ORDER BY age_band, gender;

-- Q4: Average length of stay by admission type
SELECT admission_type,
       COUNT(*)                        AS discharges,
       ROUND(AVG(length_of_stay), 1)   AS avg_days
FROM admissions
WHERE admission_status = 'Discharged'
GROUP BY admission_type
ORDER BY avg_days DESC;

-- Q5: Admissions per doctor, by department (departments with at least 10 doctors)
WITH per_doctor AS (
    SELECT admitting_doctor_id AS doctor_id, COUNT(*) AS admissions
    FROM admissions
    GROUP BY admitting_doctor_id
)
SELECT dep.dep_name                                              AS department,
       COUNT(doc.doctor_id)                                      AS doctors,
       SUM(COALESCE(p.admissions, 0))                            AS admissions,
       ROUND(1.0 * SUM(COALESCE(p.admissions, 0)) / COUNT(doc.doctor_id), 1) AS admissions_per_doctor
FROM doctors doc
JOIN departments dep USING (department_id)
LEFT JOIN per_doctor p ON p.doctor_id = doc.doctor_id
GROUP BY dep.dep_name
HAVING COUNT(doc.doctor_id) >= 10
ORDER BY admissions_per_doctor DESC;

-- Q6: The five most common diagnoses in each department
WITH counts AS (
    SELECT d.dep_name AS department, l.diagnosis_name, COUNT(*) AS n
    FROM diagnoses dx
    JOIN admissions a   ON a.admission_id   = dx.admission_id
    JOIN departments d  ON d.department_id  = a.department_id
    JOIN icd10_lookup l ON l.icd10_code     = dx.icd10_code
    GROUP BY d.dep_name, l.diagnosis_name
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY department ORDER BY n DESC, diagnosis_name) AS rnk
    FROM counts
)
SELECT department, rnk, diagnosis_name, n
FROM ranked
WHERE rnk <= 5
ORDER BY department, rnk;

-- Q7: Total billed per department per month
SELECT strftime('%Y-%m', b.bill_date) AS month,
       d.dep_name                      AS department,
       ROUND(SUM(b.total_amount), 2)   AS billed
FROM billing b
JOIN admissions a  ON a.admission_id  = b.admission_id
JOIN departments d ON d.department_id = a.department_id
GROUP BY month, department
ORDER BY month, department;

-- Q8: The three most common procedures for each kind of primary diagnosis
-- (the kind is the first letter of the ICD-10 code: I = circulatory, J = respiratory, ...)
WITH counts AS (
    SELECT substr(dx.icd10_code, 1, 1) AS chapter,
           pr.procedure_name,
           COUNT(*)                     AS n
    FROM diagnoses dx
    JOIN patient_procedures pp ON pp.admission_id = dx.admission_id
    JOIN procedures pr         ON pr.procedure_id = pp.procedure_id
    WHERE dx.diagnosis_type = 'Primary'
    GROUP BY chapter, pr.procedure_name
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY chapter ORDER BY n DESC, procedure_name) AS rnk
    FROM counts
)
SELECT chapter, rnk, procedure_name, n
FROM ranked
WHERE rnk <= 3
ORDER BY chapter, rnk;

-- Q9: The share of each department's discharged admissions that began within 30 days of the
-- same patient's previous discharge
WITH stays AS (
    SELECT department_id, admission_date,
           LAG(discharge_date) OVER (PARTITION BY patient_id ORDER BY admission_date) AS prev_discharge
    FROM admissions
    WHERE admission_status = 'Discharged'
)
SELECT d.dep_name AS department,
       COUNT(*)   AS discharged_admissions,
       SUM(prev_discharge IS NOT NULL
           AND julianday(admission_date) - julianday(prev_discharge) <= 30) AS within_30_days,
       ROUND(100.0 * SUM(prev_discharge IS NOT NULL
                         AND julianday(admission_date) - julianday(prev_discharge) <= 30) / COUNT(*), 1) AS pct
FROM stays
JOIN departments d USING (department_id)
GROUP BY d.dep_name
ORDER BY pct DESC;

-- Q10: Month-over-month change in billed revenue, with a running total
WITH monthly AS (
    SELECT strftime('%Y-%m', bill_date) AS month, SUM(total_amount) AS billed
    FROM billing
    GROUP BY month
)
SELECT month,
       ROUND(billed, 2)                                                   AS billed,
       ROUND(billed - LAG(billed) OVER (ORDER BY month), 2)               AS change_from_previous,
       ROUND(100.0 * (billed - LAG(billed) OVER (ORDER BY month))
             / LAG(billed) OVER (ORDER BY month), 1)                      AS pct_change,
       ROUND(SUM(billed) OVER (ORDER BY month), 2)                        AS running_total
FROM monthly
ORDER BY month;

-- Q11: Daily census and bed occupancy
-- Patients in a bed at midnight, and that as a percentage of inpatient beds.
WITH RECURSIVE bounds AS (
    SELECT date(MIN(admission_date)) AS first_day,
           date(MAX(COALESCE(discharge_date, admission_date))) AS last_day
    FROM admissions
    WHERE admission_status IN ('Admitted', 'Discharged')
),
days(day) AS (
    SELECT first_day FROM bounds
    UNION ALL
    SELECT date(day, '+1 day') FROM days, bounds WHERE day < last_day
),
stays AS (
    SELECT a.admission_date, COALESCE(a.discharge_date, '9999-12-31') AS ended
    FROM admissions a
    JOIN rooms r ON r.room_id = a.room_id
    WHERE a.admission_status IN ('Admitted', 'Discharged')
      AND r.room_type IN ('Standard', 'Private', 'ICU', 'NICU', 'Isolation')
),
beds AS (
    SELECT SUM(bed_capacity) AS total
    FROM rooms
    WHERE room_type IN ('Standard', 'Private', 'ICU', 'NICU', 'Isolation')
)
SELECT days.day,
       COUNT(stays.admission_date)                              AS census,
       ROUND(100.0 * COUNT(stays.admission_date) / beds.total, 1) AS occupancy_pct
FROM days
CROSS JOIN beds
LEFT JOIN stays ON stays.admission_date <= days.day AND stays.ended > days.day
GROUP BY days.day
ORDER BY days.day;

-- Q12: Doctors in the busiest tenth of their own department
WITH doctor_load AS (
    SELECT doc.doctor_id, doc.department_id, COUNT(a.admission_id) AS admissions
    FROM doctors doc
    LEFT JOIN admissions a ON a.admitting_doctor_id = doc.doctor_id
    GROUP BY doc.doctor_id, doc.department_id
),
ranked AS (
    SELECT *, PERCENT_RANK() OVER (PARTITION BY department_id ORDER BY admissions) AS pr
    FROM doctor_load
)
SELECT d.dep_name AS department, doctor_id, admissions, ROUND(pr, 2) AS pct_rank
FROM ranked
JOIN departments d USING (department_id)
WHERE pr >= 0.9
ORDER BY department, admissions DESC, doctor_id;

-- Q13: Hours worked on night shifts by nurse position
-- staff_shifts.staff_id is a doctor, nurse or employee depending on staff_type.
SELECT n.position,
       COUNT(*)                     AS night_shifts,
       ROUND(SUM(sh.hours_worked))  AS hours
FROM staff_shifts sh
JOIN nurses n ON n.nurse_id = sh.staff_id
WHERE sh.staff_type = 'Nurse'
  AND sh.shift_type = 'Night'
GROUP BY n.position
ORDER BY hours DESC;

-- Q14: The ten primary diagnoses with the highest average bill, against the overall median bill
WITH ordered AS (
    SELECT total_amount,
           ROW_NUMBER() OVER (ORDER BY total_amount) AS rn,
           COUNT(*) OVER ()                          AS n
    FROM billing
),
median AS (
    SELECT AVG(total_amount) AS median_bill
    FROM ordered
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
)
SELECT l.diagnosis_name,
       COUNT(*)                          AS bills,
       ROUND(AVG(b.total_amount), 2)     AS avg_bill,
       ROUND(AVG(b.total_amount) / median.median_bill, 2) AS times_the_median
FROM billing b
JOIN diagnoses dx   ON dx.admission_id = b.admission_id AND dx.diagnosis_type = 'Primary'
JOIN icd10_lookup l ON l.icd10_code = dx.icd10_code
CROSS JOIN median
GROUP BY l.diagnosis_name
HAVING COUNT(*) >= 20
ORDER BY avg_bill DESC
LIMIT 10;

-- Q15: Admissions discharged before they were admitted (should return no rows)
SELECT admission_id, admission_date, discharge_date
FROM admissions
WHERE discharge_date < admission_date;

-- Q16: Diagnoses made by a doctor before the doctor's hire date (should return no rows)
SELECT dx.diagnosis_id, dx.diagnosis_date, doc.hire_date
FROM diagnoses dx
JOIN doctors doc ON doc.doctor_id = dx.doctor_id
WHERE dx.diagnosis_date < doc.hire_date;

-- Q17: Diagnoses that contradict the patient's sex (should return no rows)
-- Pregnancy codes (O...) and breast cancer (C50...) on male patients, prostate cancer (C61) on female patients.
SELECT dx.diagnosis_id, dx.icd10_code, p.gender
FROM diagnoses dx
JOIN admissions a ON a.admission_id = dx.admission_id
JOIN patients p   ON p.patient_id   = a.patient_id
WHERE (p.gender = 'M' AND (dx.icd10_code LIKE 'O%' OR dx.icd10_code LIKE 'C50%'))
   OR (p.gender = 'F' AND dx.icd10_code LIKE 'C61%');

-- Q18: Rooms holding more patients at once than they have beds (should return no rows)
SELECT a.admission_id, a.room_id, a.admission_date
FROM admissions a
JOIN rooms r ON r.room_id = a.room_id
WHERE (SELECT COUNT(*)
       FROM admissions b
       WHERE b.room_id = a.room_id
         AND b.admission_date <= a.admission_date
         AND COALESCE(b.discharge_date, '9999-12-31') > a.admission_date) > r.bed_capacity;
