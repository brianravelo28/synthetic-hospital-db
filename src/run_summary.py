"""
run_summary.py
==============
The figures the documentation quotes about a run, computed once by the pipeline and written
to files the docs and the tests can read:

  * occupancy_summary(): rooms, beds, census, bed occupancy and what keeping rooms within
    capacity cost (the allocator's counts), for one size. Written by run_pipeline.py as
    <report stem>_occupancy.json next to the validation report.
  * write_checksums(): a SHA-256 for every exported CSV (app/data/checksums.json), the data
    version a reader can verify.

The census calculation matches app/utils.py (daily_census); tests/test_run_summary.py checks
the two agree on the shipped data.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

INPATIENT_ROOM_TYPES = ["Standard", "Private", "ICU", "NICU", "Isolation"]
WARMUP_DAYS = 45          # the hospital starts empty, so the first stretch is left out of averages


def daily_census(admissions: pd.DataFrame, rooms: pd.DataFrame, as_of) -> pd.DataFrame:
    """Patients in an inpatient bed at midnight, by room type, one row per day."""
    stays = admissions[admissions["admission_status"].isin(["Admitted", "Discharged"]) & admissions["room_id"].notna()]
    stays = stays.merge(rooms[["room_id", "room_type"]], on="room_id")
    stays = stays[stays["room_type"].isin(INPATIENT_ROOM_TYPES)]
    first = stays["admission_date"].min().normalize()
    days = pd.date_range(first, pd.Timestamp(as_of).normalize(), freq="D")
    one_day = pd.Timedelta(days=1)
    start = np.ceil(((stays["admission_date"] - first) / one_day).to_numpy()).astype(int)
    end = np.ceil(((stays["discharge_date"].fillna(pd.Timestamp(as_of)) - first) / one_day).to_numpy()).astype(int)
    out = {}
    for room_type in INPATIENT_ROOM_TYPES:
        pick = (stays["room_type"] == room_type).to_numpy()
        change = np.zeros(len(days) + 1)
        np.add.at(change, np.clip(start[pick], 0, len(days)), 1)
        np.add.at(change, np.clip(end[pick], 0, len(days)), -1)
        out[room_type] = np.cumsum(change)[: len(days)]
    return pd.DataFrame(out, index=days)


def occupancy_summary(admissions: pd.DataFrame, rooms: pd.DataFrame, as_of, allocation: dict) -> dict:
    """
    One size's occupancy and allocation figures.

    `allocation` holds the allocator's counts (data/occupancy.py allocate_rooms): needed_bed,
    placed, waited, wait_hours, lowered, cancelled, patient_moved. Every rate is a share of
    `needed_bed`, the admissions that needed a bed (those that happened, plus the ones cancelled
    for lack of one).
    """
    beds = (rooms[rooms["room_type"].isin(INPATIENT_ROOM_TYPES)]
            .groupby("room_type")["bed_capacity"].sum().reindex(INPATIENT_ROOM_TYPES).fillna(0))
    census = daily_census(admissions, rooms, as_of).iloc[WARMUP_DAYS:]
    total = census.sum(axis=1)
    needed = int(allocation.get("needed_bed", 0)) or 1
    waited = int(allocation.get("waited", 0))
    pct = lambda n: round(100 * n / needed, 2)          # noqa: E731
    return {
        "as_of": pd.Timestamp(as_of).strftime("%Y-%m-%d %H:%M:%S"),
        "warmup_days": WARMUP_DAYS,
        "rooms": int(len(rooms)),
        "inpatient_beds": int(beds.sum()),
        "beds_by_type": {t: int(beds[t]) for t in INPATIENT_ROOM_TYPES},
        "average_census": round(float(total.mean()), 1),
        "average_occupancy_pct": round(100 * float(total.mean()) / float(beds.sum()), 1),
        "busiest_day_pct": round(100 * float(total.max()) / float(beds.sum()), 1),
        "occupancy_by_type_pct": {t: (round(100 * float(census[t].mean()) / float(beds[t]), 1) if beds[t] else None)
                                  for t in INPATIENT_ROOM_TYPES},
        "condition_mix_pct": {k: round(100 * v, 1)
                              for k, v in admissions["patient_condition"].value_counts(normalize=True).items()},
        "admissions_by_status": {k: int(v) for k, v in admissions["admission_status"].value_counts().items()},
        "allocation": {
            "needed_bed": int(allocation.get("needed_bed", 0)),
            "placed": int(allocation.get("placed", 0)),
            "waited": waited,
            "mean_wait_hours": round(float(allocation.get("wait_hours", 0.0)) / waited, 1) if waited else 0.0,
            "lowered_care_level": int(allocation.get("lowered", 0)),
            "cancelled_for_no_bed": int(allocation.get("cancelled", 0)),
            "moved_after_patients_previous_stay": int(allocation.get("patient_moved", 0)),
            "pct_of_needed_bed": {
                "waited": pct(waited),
                "lowered_care_level": pct(int(allocation.get("lowered", 0))),
                "cancelled_for_no_bed": pct(int(allocation.get("cancelled", 0))),
                "moved_after_patients_previous_stay": pct(int(allocation.get("patient_moved", 0))),
            },
        },
    }


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_checksums(data_dir: Path, names: list) -> dict:
    """Write data_dir/checksums.json: the SHA-256 of each exported CSV."""
    files = {f"{n}.csv": file_sha256(data_dir / f"{n}.csv") for n in names}
    manifest = {"algorithm": "sha256", "files": files}
    with open(data_dir / "checksums.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest
