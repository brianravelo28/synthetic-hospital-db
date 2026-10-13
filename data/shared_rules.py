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
