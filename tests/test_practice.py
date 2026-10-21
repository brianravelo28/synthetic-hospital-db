"""The practice set (practice/): the SQLite loader, and that every solution runs and means what it says."""

import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRACTICE = ROOT / "practice"
sys.path.insert(0, str(PRACTICE))

import load_sqlite  # noqa: E402


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    db = tmp_path_factory.mktemp("practice") / "hospital.db"
    counts = load_sqlite.build(db)
    assert counts["admissions"] > 0
    return sqlite3.connect(db)


def _solutions():
    text = (PRACTICE / "solutions.sql").read_text(encoding="utf-8")
    parts = re.split(r"^-- (Q\d+): ", text, flags=re.M)
    return {parts[i]: parts[i + 1].partition("\n")[2] for i in range(1, len(parts), 2)}


def test_loader_builds_every_table_with_the_csv_row_counts(con):
    import pandas as pd
    for table in load_sqlite.TABLES:
        n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        assert n == len(pd.read_csv(load_sqlite.DATA / f"{table}.csv")), table


def test_questions_and_solutions_cover_the_same_numbers():
    questions = (PRACTICE / "questions.md").read_text(encoding="utf-8")
    asked = [int(n) for n in re.findall(r"^(\d+)\. ", questions, flags=re.M)]
    assert asked == list(range(1, 19))
    assert sorted(_solutions(), key=lambda q: int(q[1:])) == [f"Q{n}" for n in range(1, 19)]


@pytest.mark.parametrize("name", [f"Q{n}" for n in range(1, 15)])
def test_each_analysis_solution_runs_and_returns_rows(con, name):
    rows = con.execute(_solutions()[name]).fetchall()
    assert len(rows) > 0


@pytest.mark.parametrize("name", ["Q15", "Q16", "Q17", "Q18"])
def test_each_data_quality_solution_returns_no_rows(con, name):
    assert con.execute(_solutions()[name]).fetchall() == []


def test_daily_census_solution_matches_the_pandas_calculation(con):
    """Q11 (SQL) and the dashboard's census function (pandas) count the same stays the same way."""
    import pandas as pd
    sys.path.insert(0, str(ROOT / "app"))
    import utils
    rows = con.execute(_solutions()["Q11"]).fetchall()
    sql = {day: census for day, census, _ in rows}
    adm = pd.read_csv(ROOT / "app" / "data" / "admissions.csv", parse_dates=["admission_date", "discharge_date"])
    rooms = pd.read_csv(ROOT / "app" / "data" / "rooms.csv")
    as_of = pd.Timestamp(__import__("json").loads((ROOT / "app" / "data" / "validation_report_meta.json").read_text())["as_of"])
    census = utils.daily_census(adm, rooms, as_of).sum(axis=1)
    for day in list(sql)[50::40]:
        assert sql[day] == census[pd.Timestamp(day)], day
