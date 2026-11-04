# Data Sources & References

## Synthetic data disclosure

**Every row in this project is generated, not real.** No patient records, hospital records, or any other real-world personal or protected health information (PHI) were used, sourced, or referenced in building the generator or the data it produces. Patient names, SSNs, addresses, and dates are produced by [Faker](https://faker.readthedocs.io/); clinical, staffing, and financial values are produced by the weighted-random logic in `data/hospital_generator.py`. Any resemblance between a generated record and a real person is coincidental.

## What is based on what

| Part | Basis |
|---|---|
| **Table and field layout** | Follows published hospital-database designs (next section). |
| **Codes and scales** | Real ICD-10-CM diagnosis codes, CPT-style procedure codes (format only) and the Emergency Severity Index triage scale. |
| **Every number and proportion** | Random draws from settings the author chose. None is measured from real hospitals. See "Numbers and proportions" below. |
| **The 59 checks** | Rules the author wrote. They test that the tables agree with each other, not that the data is clinically realistic. |

## Database structure: design references

The choice of tables and fields (patients, doctors, nurses, departments, rooms, admissions, diagnoses, procedures, medications, tests, billing and so on) follows hospital-database designs in the sources below. They are design references, not data sources: no data was taken from them, and they describe how a hospital database is organised, not how real hospitals behave. They differ in kind: two are journal papers, one is a short overview, one is a tutorial exercise set and one is a student project report.

- [w3resource: Hospital database SQL exercises](https://www.w3resource.com/sql-exercises/hospital-database-exercise/index.php): a 15-table practice database (physicians, departments, patients, nurses, appointments, medications, rooms, stays, procedures). The page says its structure is adapted from a Wikibooks SQL exercise.
- Amaechi, J. C., Agbasonu, V. C., and Nwawudu, S. E. (2018). [Design and Implementation of a Hospital Database Management System (HDMS) for Medical Doctors](https://www.ijcte.org/vol10/1190-D3004.pdf). *International Journal of Computer Theory and Engineering*, 10(1). Includes table designs for patient records, triage, tests and bills.
- Tripathee, D. (2016). [Hospital Database Management System](https://www.ijcsmc.com/docs/papers/April2016/V5I4201602.pdf). *International Journal of Computer Science and Mobile Computing*, 5(4), 71–73. A short overview that lists the entities such a database holds (doctors, patients, visits, insurance, bills, diagnoses, prescriptions and others).
- Sarder, F. (2020). [Hospital Database Management System (SQL project report)](https://www.academia.edu/43576204/Hospital_Database_Management_System_sql_project_report_). City University Dhaka, student project report on Academia.edu.
- [Hospital Database Relationship Design](https://www.researchgate.net/figure/Hospital-Database-Relationship-Design_fig5_242421198): a relationship diagram on ResearchGate.
- **Gender and sex at birth.** `patients.gender` (identity) and `patients.sex_at_birth` are separate fields because the sex-specific clinical rules (pregnancy, prostate disease, deliveries, Pap smears) depend on sex at birth, not gender identity. Splitting them follows the separate "Sex (assigned at birth)" and "Gender Identity" data elements in the Patient Demographics class of [USCDI Version 2](https://www.healthit.gov/isa/sites/isa/files/2021-07/USCDI-Version-2-July-2021-Final.pdf) (ONC, July 2021). Later USCDI versions list a single "Sex" element. In this dataset sex at birth equals gender for M and F patients and is drawn 50/50 for NB patients, a simplification the author chose.

## Coding standards and scales

These make the data look like hospital data. They are not sourced from real records.

- **ICD-10-CM** (diagnosis coding): [CDC/NCHS ICD-10-CM overview](https://www.cdc.gov/nchs/icd/icd-10-cm.htm). `data/icd10_diagnoses.py` hand-curates 66 real ICD-10-CM codes. The *codes* are real; the weights and the records that use them are not (see below).
- **CPT-style procedure codes**: [AMA CPT overview](https://www.ama-assn.org/practice-management/cpt). `data/hospital_generator.py`'s procedure catalog mimics CPT code formatting for realism only; it is not licensed CPT content and is not a billing reference.
- **Emergency Severity Index (ESI)**: the published five-level triage scale (1 most urgent, 5 least) used for triage acuity. The levels are real; how often each occurs here is hand-set.
- **HIPAA Safe Harbor de-identification** ([HHS guidance](https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html)): informed the general shape of what fields a hospital dataset "should" contain, as a design reference. This project makes no claim of HIPAA compliance, since there is no real data to be compliant *about*.

## Numbers and proportions: chosen, not sourced

Every number below is a setting the author chose, tuned so that the output looks plausible. None comes from a study or from any hospital's figures, and none makes a claim of statistical accuracy.

- Diagnosis weights (2.5 to 9.5, common conditions higher) and which department each code belongs to
- Age mix (`AGE_BANDS`), gender proportions (48% M, 48% F, 4% NB), blood-type and state mixes
- Admission-type mix, patient-condition mix, stay lengths, and how many admissions are scheduled or cancelled
- Occupancy targets by room type and the room counts they produce
- Insurance coverage rates by payer, charges per procedure and per room-day, and the 0 to 90 day lag between discharge and bill
- Staff counts, hire dates, shift patterns, and vitals ranges by age band
- Which procedures, drugs and tests go with which diagnosis (a coarse hand-built table, not clinical guidance)

Findings from the data (for example, "Emergency Medicine has the most admissions") therefore describe this dataset, not the real world.

## Tooling

- Faker (synthetic PII generation): https://faker.readthedocs.io/
- SQLAlchemy (database toolkit): https://www.sqlalchemy.org/
- PyMySQL (MySQL driver): https://pymysql.readthedocs.io/
- pandas / NumPy: https://pandas.pydata.org/ · https://numpy.org/
- Streamlit (dashboard framework): https://streamlit.io/
- Plotly (charting): https://plotly.com/python/
- Jupyter (notebooks): https://jupyter.org/
