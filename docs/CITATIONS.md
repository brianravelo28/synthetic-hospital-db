# Data Sources & References

## Synthetic data disclosure

**Every row in this project is generated, not real.** No patient records, hospital records, or any other real-world personal or protected health information (PHI) were used, sourced, or referenced in building the generator or the data it produces. Patient names, SSNs, addresses, and dates are produced by [Faker](https://faker.readthedocs.io/); clinical, staffing, and financial values are produced by the weighted-random logic in `data/hospital_generator.py`. Any resemblance between a generated record and a real person is coincidental.

## Coding standards referenced (for realism, not sourced from real records)

- **ICD-10-CM** (diagnosis coding): [CDC/NCHS ICD-10-CM overview](https://www.cdc.gov/nchs/icd/icd-10-cm.htm). `data/icd10_diagnoses.py` hand-curates 66 real ICD-10-CM codes with approximate real-world prevalence weights (CMS/HCUP-style ordering) so diagnosis distributions look realistic — the *codes* are real; the *records* using them are not.
- **CPT-style procedure codes**: [AMA CPT overview](https://www.ama-assn.org/practice-management/cpt) — `data/hospital_generator.py`'s procedure catalog mimics CPT code formatting for realism only; it is not licensed CPT content and is not a billing reference.
- **HIPAA Safe Harbor de-identification** ([HHS guidance](https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html)): informed the general shape of what fields a hospital dataset "should" contain, as a design reference — this project makes no claim of HIPAA compliance, since there's no real data to be compliant *about*.

## Tooling

- Faker (synthetic PII generation): https://faker.readthedocs.io/
- SQLAlchemy (database toolkit): https://www.sqlalchemy.org/
- PyMySQL (MySQL driver): https://pymysql.readthedocs.io/
- pandas / NumPy: https://pandas.pydata.org/ · https://numpy.org/
- Streamlit (dashboard framework): https://streamlit.io/
- Plotly (charting): https://plotly.com/python/
- Jupyter (notebooks): https://jupyter.org/
