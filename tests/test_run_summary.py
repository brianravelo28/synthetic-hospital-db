"""
The figures the docs quote about a run come from files the pipeline writes
(app/data/validation_report_occupancy.json and app/data/checksums.json). These tests
recompute them from the shipped CSVs, so the files cannot drift from the data.
No database needed.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

import run_summary as rs

DATA = Path(__file__).resolve().parent.parent / "app" / "data"
RUNS = Path(__file__).resolve().parent.parent / "docs" / "validation_runs"


@pytest.fixture(scope="module")
def shipped():
    adm = pd.read_csv(DATA / "admissions.csv", parse_dates=["admission_date", "discharge_date"])
    rooms = pd.read_csv(DATA / "rooms.csv")
    recorded = json.loads((DATA / "validation_report_occupancy.json").read_text(encoding="utf-8"))
    return adm, rooms, recorded


def test_census_matches_the_dashboards(shipped):
    utils = pytest.importorskip("streamlit") and __import__("utils")
    adm, rooms, recorded = shipped
    mine = rs.daily_census(adm, rooms, recorded["as_of"])
    theirs = utils.daily_census(adm, rooms, pd.Timestamp(recorded["as_of"]))
    pd.testing.assert_frame_equal(mine, theirs)


def test_recorded_occupancy_is_recomputed_from_the_shipped_csvs(shipped):
    adm, rooms, recorded = shipped
    again = rs.occupancy_summary(adm, rooms, recorded["as_of"], {
        "needed_bed": recorded["allocation"]["needed_bed"],
        "placed": recorded["allocation"]["placed"],
        "waited": recorded["allocation"]["waited"],
        "wait_hours": recorded["allocation"]["mean_wait_hours"] * recorded["allocation"]["waited"],
        "lowered": recorded["allocation"]["lowered_care_level"],
        "cancelled": recorded["allocation"]["cancelled_for_no_bed"],
        "patient_moved": recorded["allocation"]["moved_after_patients_previous_stay"],
    })
    for key in ("rooms", "inpatient_beds", "beds_by_type", "average_census", "average_occupancy_pct",
                "busiest_day_pct", "occupancy_by_type_pct", "condition_mix_pct", "admissions_by_status"):
        assert again[key] == recorded[key], key


def test_allocation_counts_are_consistent_with_the_data_and_each_other(shipped):
    adm, _, recorded = shipped
    a = recorded["allocation"]
    happened = int(adm["admission_status"].isin(["Admitted", "Discharged"]).sum())
    assert a["placed"] == happened                                    # every placed stay is in the CSV
    assert a["needed_bed"] == a["placed"] + a["cancelled_for_no_bed"]  # the base of every rate
    # the stays cancelled for lack of a bed are among the CSV's Cancelled rows
    assert a["cancelled_for_no_bed"] <= int((adm["admission_status"] == "Cancelled").sum())
    for name, rate in a["pct_of_needed_bed"].items():
        assert rate == pytest.approx(round(100 * a[name] / a["needed_bed"], 2)), name


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_every_size_has_a_recorded_occupancy_summary(size):
    recorded = json.loads((RUNS / f"{size}_occupancy.json").read_text(encoding="utf-8"))
    a = recorded["allocation"]
    assert a["needed_bed"] == a["placed"] + a["cancelled_for_no_bed"] > 0
    assert 0 < recorded["average_occupancy_pct"] < 100
    assert recorded["inpatient_beds"] == sum(recorded["beds_by_type"].values())


def test_large_summary_in_docs_equals_the_one_next_to_the_data():
    assert (RUNS / "large_occupancy.json").read_text(encoding="utf-8") == \
        (DATA / "validation_report_occupancy.json").read_text(encoding="utf-8")


def test_the_data_version_is_checksummed_and_the_csvs_match():
    manifest = json.loads((DATA / "checksums.json").read_text(encoding="utf-8"))
    assert manifest["algorithm"] == "sha256"
    assert len(manifest["files"]) == 18                               # 17 tables + the ICD-10 lookup
    for name, digest in manifest["files"].items():
        assert rs.file_sha256(DATA / name) == digest, f"{name} changed since the checksums were written"


def test_peak_census_of_each_room_type_never_exceeds_its_beds(shipped):
    """No room type is ever over capacity on any day (the check is per type, not only for the hospital)."""
    adm, rooms, recorded = shipped
    census = rs.daily_census(adm, rooms, recorded["as_of"])
    for room_type, beds in recorded["beds_by_type"].items():
        assert census[room_type].max() <= beds, room_type
