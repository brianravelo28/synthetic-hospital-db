# Using the solutions on MySQL or MariaDB

`solutions.sql` is written for SQLite, so it runs on the database you can build with `load_sqlite.py` and needs no server. The schema in `data/hospital_db.sql` is MySQL/MariaDB, and most solutions run unchanged on it (the solutions were checked against MariaDB 10.4, which has window functions and recursive CTEs; MySQL 8 has both too). A few use SQLite-only date functions. Here are the replacements.

| SQLite | MySQL / MariaDB |
|---|---|
| `strftime('%Y-%m', x)` | `DATE_FORMAT(x, '%Y-%m')` |
| `julianday(a) - julianday(b)` | `TIMESTAMPDIFF(HOUR, b, a) / 24` (or `DATEDIFF(a, b)` for whole calendar days) |
| `date(day, '+1 day')` | `DATE_ADD(day, INTERVAL 1 DAY)` |
| `date(x)` | `DATE(x)` |
| `substr(x, 1, 1)` | `SUBSTRING(x, 1, 1)` (`SUBSTR` also works) |
| `'9999-12-31'` as a "still admitted" end date | the same literal works with `DATETIME` columns |

Three other differences worth knowing:

- **Dates are real types in MySQL.** In SQLite the dates are text in ISO format, which compares correctly. In MySQL the columns are `DATE` / `DATETIME`, so comparisons and `COALESCE(discharge_date, '9999-12-31')` behave the same way.
- **`GROUP BY` strictness.** MySQL's default `ONLY_FULL_GROUP_BY` mode rejects a select list that mentions a non-aggregated column not in the `GROUP BY`. The solutions group by every non-aggregated column, so this should not bite.
- **Booleans as numbers.** `SUM(a > b)` works in both; MySQL returns a decimal where SQLite returns an integer, so counts print as `73` in SQLite and may print as `73` or `73.0` in a client.

## The statements that change

**Q7** (billed per department per month):

```sql
SELECT DATE_FORMAT(b.bill_date, '%Y-%m') AS month,
       d.dep_name                          AS department,
       ROUND(SUM(b.total_amount), 2)       AS billed
FROM billing b
JOIN admissions a  ON a.admission_id  = b.admission_id
JOIN departments d ON d.department_id = a.department_id
GROUP BY month, department
ORDER BY month, department;
```

**Q9** (30-day repeat admissions by department): replace the two `julianday` differences with `TIMESTAMPDIFF(HOUR, prev_discharge, admission_date) <= 30 * 24`.

**Q10** (month-over-month revenue): replace `strftime('%Y-%m', bill_date)` with `DATE_FORMAT(bill_date, '%Y-%m')`; the rest is unchanged.

**Q11** (daily census): the date series and the day arithmetic change.

```sql
WITH RECURSIVE bounds AS (
    SELECT DATE(MIN(admission_date)) AS first_day,
           DATE(MAX(COALESCE(discharge_date, admission_date))) AS last_day
    FROM admissions
    WHERE admission_status IN ('Admitted', 'Discharged')
),
days(day) AS (
    SELECT first_day FROM bounds
    UNION ALL
    SELECT DATE_ADD(day, INTERVAL 1 DAY) FROM days, bounds WHERE day < last_day
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
       COUNT(stays.admission_date)                                AS census,
       ROUND(100.0 * COUNT(stays.admission_date) / beds.total, 1) AS occupancy_pct
FROM days
CROSS JOIN beds
LEFT JOIN stays ON stays.admission_date <= days.day AND stays.ended > days.day
GROUP BY days.day
ORDER BY days.day;
```

**Q6 and Q14 need the `icd10_lookup` table**, which is not part of the MySQL schema: it ships as `app/data/icd10_lookup.csv` (exported from the generator's code catalog, and loaded automatically by `load_sqlite.py`). To use those two solutions on MySQL or MariaDB, create and fill it first with the script in this folder:

```bash
mysql -u root hospital_db < practice/icd10_lookup.sql
```

Every other solution (Q1 to Q5, Q8, Q12 to Q18) runs as written.
