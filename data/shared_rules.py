"""
shared_rules.py
===============
Single source of truth for everything the generator and the validator must
agree on. Both used to carry their own copies ("must match" comments); now they
import from here, so they can't drift apart.

Also holds the pipeline's reference date, AS_OF: the moment that "now" means
for the whole run (generator dates, validator SQL, repair). By default it is
the wall-clock time at import, rounded to the second. Set HOSPITAL_AS_OF
(e.g. 2026-10-13 or "2026-10-13 12:00:00") to pin it, which — together with the
fixed seeds — makes two runs byte-for-byte identical.
"""

import os
from datetime import datetime


def _as_of() -> datetime:
    raw = os.environ.get("HOSPITAL_AS_OF")
    if raw:
        return datetime.fromisoformat(raw)
    return datetime.now().replace(microsecond=0)


AS_OF     = _as_of()
AS_OF_SQL = "'" + AS_OF.strftime("%Y-%m-%d %H:%M:%S") + "'"     # literal for SQL strings

# Allowed room types per patient condition
CONDITION_ROOM_MAP = {
    'Intensive': ['ICU', 'NICU'],
    'Maximum':   ['ICU', 'NICU', 'Private', 'Isolation'],
    'Moderate':  ['Standard', 'Private'],
    'Minimal':   ['Standard', 'Recovery', 'Private'],
}

# ICD-10 codes that are biologically impossible for certain genders/ages
MALE_IMPOSSIBLE_CODES   = {'O80', 'O34.21', 'O09.90', 'O20.0', 'C50.919'}
FEMALE_IMPOSSIBLE_CODES = {'C61'}
NEWBORN_ONLY_CODES      = {'Z38.00', 'P07.30'}

# OB/GYN and newborn (Pediatrics) departments
OB_NEWBORN_DEPTS = {'DEP-008', 'DEP-009'}

# Insurance coverage rate by payer type
PAYER_COVERAGE = {
    'Medicare':             0.80,
    'Medicaid':             0.72,
    'Private Insurance':    0.85,
    'Self-Pay':             0.00,
    'Workers Compensation': 0.90,
    'CHIP':                 0.75,
}


# ── Occupancy ───────────────────────────────────────────────────────────────
# The hospital's admissions cover the last year, and rooms are sized from the
# expected patient load so the wards run busy instead of nearly empty.
# (data/occupancy.py does the sizing and the room allocation.)

ADMISSION_WINDOW_DAYS = 365          # admissions run from AS_OF minus this, up to AS_OF

# Beds per room, by room type
ROOM_BEDS = {'Standard': 2, 'Private': 1, 'ICU': 1, 'NICU': 1,
             'OR': 1, 'ER': 2, 'Recovery': 2, 'Isolation': 1}

# Room types a patient can occupy. OR, ER and Recovery are procedure and visit
# spaces, not inpatient beds: they exist as rooms but never hold an admission,
# and they are not counted in inpatient bed capacity.
INPATIENT_ROOM_TYPES = ('Standard', 'Private', 'ICU', 'NICU', 'Isolation')

# Where each patient condition goes first. Every type listed here is allowed for
# that condition by CONDITION_ROOM_MAP (a unit test checks this).
ROOM_ROUTING = {
    'Intensive': {'ICU': 0.85, 'NICU': 0.15},
    'Maximum':   {'ICU': 0.30, 'Private': 0.45, 'Isolation': 0.20, 'NICU': 0.05},
    'Moderate':  {'Standard': 0.65, 'Private': 0.35},
    'Minimal':   {'Standard': 0.70, 'Private': 0.30},
}

# Planned average bed occupancy by room type (an author's choice, not a benchmark):
# intensive care runs busier than a general ward. The rooms are sized so the
# expected load meets these; the realised figures are measured, not assumed.
OCCUPANCY_TARGET = {'Standard': 0.60, 'Private': 0.58, 'ICU': 0.78, 'NICU': 0.75, 'Isolation': 0.55}

# Rooms are sized against OCCUPANCY_TARGET times this factor. Rounding up to whole rooms and the
# empty first days of the window leave the realised occupancy below plan, so the rooms are cut a
# little tighter; what is reported is always the realised figure, measured from the data.
OCCUPANCY_SIZING_FACTOR = 1.10

# A patient with no suitable bed free waits for one, up to this long, before being placed at a
# lower level of care. Each department's rooms are a separate pool and small pools are often full,
# so some waiting is unavoidable at any realistic occupancy.
MAX_BED_WAIT_HOURS = 168

# Procedure and visit rooms per hospital size, and the departments that hold them
NON_INPATIENT_ROOMS = {
    'small':  {'OR': 2,  'ER': 1, 'Recovery': 2},
    'medium': {'OR': 5,  'ER': 2, 'Recovery': 4},
    'large':  {'OR': 14, 'ER': 4, 'Recovery': 10},
}
ER_DEPTS = ('DEP-001',)                                                    # Emergency Medicine
OR_DEPTS = ('DEP-004', 'DEP-007', 'DEP-003', 'DEP-020', 'DEP-009')         # surgery, ortho, cardiology, operations, OB/GYN
