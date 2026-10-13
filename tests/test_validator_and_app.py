"""Static checks on the validator's rule set and the dashboard's helpers — no database needed."""

import ast
import re
from pathlib import Path

import pytest

import validate_repair as vr

ROOT = Path(__file__).resolve().parent.parent


def _validator_rule_names():
    src = (ROOT / "src" / "validate_repair.py").read_text(encoding="utf-8")
    return re.findall(r"^\s+'([a-z0-9_]+)': _count\(", src, flags=re.M)


def _dashboard_rule_descriptions():
    tree = ast.parse((ROOT / "app" / "views" / "data_quality.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "RULE_DESCRIPTIONS":
            return ast.literal_eval(node.value)
    raise AssertionError("RULE_DESCRIPTIONS not found")


def test_rule_names_are_unique_and_there_are_51():
    names = _validator_rule_names()
    assert len(names) == len(set(names)) == 51


def test_every_rule_has_a_dashboard_description_and_vice_versa():
    assert set(_validator_rule_names()) == set(_dashboard_rule_descriptions())


def test_every_group_has_a_label():
    for key in ["group1_temporal", "group2_age", "group3_admission_type", "group4_department",
                "group5_diagnoses", "group6_financial", "group7_realism"]:
        assert key in vr.GROUP_LABELS


def test_report_to_rows_flattens_in_order():
    rows = vr.report_to_rows({"group1_temporal": {"a": 1, "b": 0}, "group7_realism": {"c": 5}})
    assert [(r["rule"], r["count"]) for r in rows] == [("a", 1), ("b", 0), ("c", 5)]
    assert rows[2]["group_label"] == vr.GROUP_LABELS["group7_realism"]


# ── dashboard helpers (app/utils.py) ─────────────────────────────────────

@pytest.fixture(scope="module")
def app_utils():
    return pytest.importorskip("streamlit") and __import__("utils")


def test_wrap_label_wraps_to_at_most_two_lines(app_utils):
    label = app_utils.wrap_label("Acute myeloblastic leukemia, not having achieved remission", width=30)
    assert label.count("<br>") == 1
    assert len(label.split("<br>")) == 2


def test_wrap_label_truncates_with_ellipsis_past_two_lines(app_utils):
    label = app_utils.wrap_label(
        "Fracture of unspecified part of neck of right femur, initial encounter", width=30)
    assert len(label.split("<br>")) == 2
    assert label.endswith("…")


def test_wrap_label_leaves_short_labels_alone(app_utils):
    assert app_utils.wrap_label("Chest pain, unspecified", width=30) == "Chest pain, unspecified"


def test_formatters(app_utils):
    assert app_utils.fmt_currency(241_000_000) == "$241.0M"
    assert app_utils.fmt_currency(12_345) == "$12K"
    assert app_utils.fmt_count(12000) == "12,000"
    assert app_utils.fmt_pct(4.66) == "4.7%"
    assert app_utils.fmt_count(float("nan")) == "—"


def test_every_categorical_color_map_value_is_a_hex_color(app_utils):
    for name in dir(app_utils):
        if name.endswith("_COLORS") and isinstance(getattr(app_utils, name), dict):
            for color in getattr(app_utils, name).values():
                assert re.fullmatch(r"#[0-9a-fA-F]{6}", color), (name, color)
