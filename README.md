# Synthetic Hospital Database

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/dashboard-Streamlit-FF4B4B.svg)](https://streamlit.io/)

**100% synthetic — no real patient data.** A constraint-aware generator for a realistic, fully-relational 17-table hospital database (MySQL), a validation/repair pipeline that catches and fixes semantic violations a naive generator can't avoid, and a 5-page operations dashboard built on top of it. Built to demonstrate data-engineering and data-quality thinking, not to model any real institution — see [Data Sources & References](docs/CITATIONS.md#synthetic-data-disclosure) for the full disclosure.

## Overview

Most synthetic-data generators produce rows that are individually plausible but collectively wrong: a newborn admitted to Cardiology, a male patient diagnosed with a pregnancy complication, a bill dated before the discharge it covers. This project builds a generator that prevents most of those violations *at generation time*, backed by a 6-rule-group validator that catches (and repairs) whatever slips through — and documents, with real numbers, exactly how much each fix actually helped.

**Real, verified results:**
- 🏥 **17-table relational schema**: departments, staff, patients, admissions, clinical records, and billing — full FK graph, `CHECK` constraints, one polymorphic reference pattern (`staff_shifts.staff_id`)
- 🐛 **A real bug found and fixed**: at small scale, 10 of 20 departments ended up with zero doctors — making a whole violation category *permanently unrepairable*, the likely root cause of the project's original "regenerate → repair → still broken" loop. See [docs/METHODOLOGY.md](docs/METHODOLOGY.md#a-fifth-bug-found-by-testing-at-small-scale).
- 📉 **Violations eliminated in a single repair pass, at every scale tested** — no regenerate loop needed:

  | Scale | Admissions | Before repair | After repair | Eliminated |
  |---|---|---|---|---|
  | Small | 800 | 1,503 | 54 | 96.4% |
  | Medium | 3,200 | 6,299 | 35 | 99.4% |
  | Large | 12,000 | 25,720 | 22 | 99.9% |

- 📊 **5-page Streamlit dashboard**, fully self-contained (bundled CSVs, no live DB dependency) — Overview, Admissions & Census, Clinical, Staffing, Financials
- 📓 **Two executed notebooks** with real, live-generated output — including a from-scratch re-run of the generate → validate → repair cycle, not a transcript

## Quick Start

```bash
git clone https://github.com/yourusername/synthetic-hospital-db.git
cd synthetic-hospital-db
pip install -r requirements.txt
```

### Generate + repair the database

Requires a local MySQL server (development used [XAMPP](https://www.apachefriends.org/)).

```bash
mysql -u root < data/hospital_db.sql

python -c "
import sys; sys.path.insert(0, 'data')
exec(open('data/hospital_generator.py').read())
main('large')   # or 'small' / 'medium'
"

python -c "
import sys; sys.path.insert(0, 'data'); sys.path.insert(0, 'src')
exec(open('src/validate_repair.py').read())
run_repair()
"
```

`hospital_generator.py` and `src/validate_repair.py` are written for `exec()`-style Jupyter usage — see the docstring at the top of each file.

### Export to CSV and launch the dashboard

```bash
python src/export_to_csv.py         # writes app/data/*.csv from the live DB
streamlit run app/app.py            # -> http://localhost:8501
```

The dashboard reads **only** the exported CSVs, never a live connection — this is what makes it deployable to [Streamlit Community Cloud](https://streamlit.io/cloud) as-is, since a deployed app can't reach a local database. `app/requirements.txt` is a separate, minimal requirements file (just `streamlit`/`pandas`/`plotly`) scoped to the dashboard alone — Streamlit Cloud installs from whichever `requirements.txt` sits next to the app's entry point, and the full pipeline's dependencies (SQLAlchemy, Faker, Jupyter...) have no reason to ship with the deployed app.

### Explore the notebooks

```bash
jupyter notebook notebooks/
```
- `01_eda_hospital_operations.ipynb` — exploratory analysis of the repaired dataset (admissions trends, department volume, diagnoses, length of stay, financials); reads only `app/data/`, no DB needed
- `02_data_quality_validation.ipynb` — a **live** re-run of the full generate → validate → repair cycle, capturing real before/after numbers (⚠️ truncates and regenerates `hospital_db` — see the notebook's own warning)

## Dashboard

5 pages, each browser-verified against real (synthetic) data:

| Page | What it shows |
|---|---|
| **Overview** | Headline KPIs, admissions trend, admission-type mix, department volume, patient condition (acuity) mix |
| **Admissions & Census** | Filterable by date/department/type — admission status, length-of-stay distribution, discharge disposition, triage acuity, day-of-week pattern |
| **Clinical** | Top diagnoses (ICD-10, human-readable names), diagnoses by department, top procedures/medications, test result severity mix |
| **Staffing** | Headcount by department (doctor/nurse/employee), doctor specialties, shift-type distribution, hires per year |
| **Financials** | Revenue by payer type, payment status mix, billing line items by type, avg. bill by admission type, revenue trend |

Colors are assigned by category identity (not chart-local rank or hue-cycling), with true evaluative "status" colors (e.g. payment status, discharge disposition) kept separate from plain categorical identity and from ordinal severity scales — see `app/utils.py`.

## Project Structure

```
synthetic-hospital-db/
├── README.md               # this file
├── requirements.txt
├── LICENSE                  # MIT
├── .gitignore
├── data/                    # schema + constraint-aware generator (the "acquisition" step for synthetic data)
│   ├── hospital_db.sql
│   ├── hospital_generator.py
│   └── icd10_diagnoses.py
├── src/                     # validation/repair pipeline + CSV export
│   ├── validate_repair.py
│   └── export_to_csv.py
├── notebooks/               # EDA and data-quality validation (executed, real outputs)
├── app/                     # Streamlit dashboard (self-contained, bundled CSVs in app/data/)
└── docs/                    # schema reference, methodology, citations
```

See [docs/SCHEMA.md](docs/SCHEMA.md) for exact table/column definitions and [docs/METHODOLOGY.md](docs/METHODOLOGY.md) for the full write-up of what was actually broken, how it was diagnosed, and how it was fixed.

## Data Sources

There are no external data sources — every row is synthetically generated (see [docs/CITATIONS.md](docs/CITATIONS.md) for the full disclosure and the coding standards referenced for realism). This is a deliberate design choice: healthcare data carries real privacy stakes, and a portfolio piece has no legitimate reason to touch real PHI.

## Status & Limitations

- **Done**: schema + constraint-aware generator, validation/repair pipeline (validated at 3 scales), CSV export, 5-page dashboard (browser-verified), 2 executed notebooks.
- **Known, disclosed residual violations** (not bugs): room-type scarcity in thin departments at small scale, and a rare double-`Newborn`-admission edge case — both explained in [docs/METHODOLOGY.md](docs/METHODOLOGY.md#results-across-scale).
- **Not automated**: the generate → repair → export cycle is run manually (see Quick Start); there's no CI/scheduled job re-running it.
- **Not deployed**: the dashboard runs locally (`streamlit run app/app.py`); it hasn't yet been pushed to Streamlit Community Cloud.
- **Financial reconciliation is repair-only, not prevented at generation** — `billing_line_items` totals are reconciled to `billing.total_amount` entirely in the repair step; see the Known Limitations section of [docs/METHODOLOGY.md](docs/METHODOLOGY.md#known-limitations) for why this was left out of scope for the generator patch.

## License

MIT License — see [LICENSE](LICENSE).
