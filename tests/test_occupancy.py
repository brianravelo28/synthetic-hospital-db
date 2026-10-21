"""Unit tests for room planning and allocation (no database needed)."""

import random
from datetime import datetime, timedelta

import pytest

import hospital_generator as gen
import occupancy as occ
import shared_rules as sr

NOW = datetime(2026, 10, 13, 12, 0, 0)
IDS = [d["department_id"] for d in gen.DEPARTMENTS_DATA]
SHARES = gen._dept_load_shares(IDS)


# ── constants agree with each other ──────────────────────────────────────

def test_routing_only_uses_room_types_the_condition_allows_and_sums_to_one():
    for cond, weights in sr.ROOM_ROUTING.items():
        assert set(weights) <= set(sr.CONDITION_ROOM_MAP[cond]), cond
        assert sum(weights.values()) == pytest.approx(1.0)
        assert set(weights) <= set(sr.INPATIENT_ROOM_TYPES)


def test_every_room_type_has_beds_and_inpatient_types_have_a_target():
    assert set(sr.ROOM_BEDS) == set(gen.ROOM_TYPES)
    assert set(sr.INPATIENT_ROOM_TYPES) <= set(sr.ROOM_BEDS)
    assert set(sr.OCCUPANCY_TARGET) == set(sr.INPATIENT_ROOM_TYPES)
    assert not set(sr.INPATIENT_ROOM_TYPES) & {'OR', 'ER', 'Recovery'}


def test_every_care_level_can_step_down_to_a_room_every_department_has():
    for condition, chain in occ.LOWER_CARE.items():
        assert chain[0] == condition and chain[-1] == 'Minimal'
    # the floor (Standard + ICU) covers Minimal/Moderate (Standard) and Maximum/Intensive (ICU)
    assert set(occ.MIN_ONE_ROOM) == {'Standard', 'ICU'}


def test_department_load_shares_sum_to_one_and_newborns_go_to_ob_and_pediatrics():
    assert sum(SHARES.values()) == pytest.approx(1.0)
    assert all(share > 0 for share in SHARES.values())
    assert SHARES['DEP-009'] > SHARES['DEP-003']          # OB/GYN also receives the newborn share


def test_expected_stay_matches_the_generator_draw():
    import numpy as np
    np.random.seed(0)
    drawn = [min(max(1, int(np.random.exponential(scale=5))), gen.MAX_STAY_DAYS) for _ in range(200_000)]
    assert occ.expected_stay_days(gen.MAX_STAY_DAYS) == pytest.approx(sum(drawn) / len(drawn), abs=0.05)


# ── planning ─────────────────────────────────────────────────────────────

def _plan(size):
    cfg = gen.HOSPITAL_SIZES[size]
    return occ.plan_rooms(SHARES, cfg['admissions'], 0.9, gen.CONDITION_P, occ.expected_stay_days(45), size)


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_every_department_gets_a_standard_and_an_icu_room(size):
    plan = _plan(size)
    for dept in IDS:
        types = {t for d, t, _ in plan if d == dept}
        assert {'Standard', 'ICU'} <= types


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_nicu_rooms_only_in_the_newborn_departments(size):
    assert {d for d, t, _ in _plan(size) if t == 'NICU'} == sr.OB_NEWBORN_DEPTS


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_procedure_rooms_follow_the_size_table(size):
    counts = {}
    for _, t, c in _plan(size):
        counts[t] = counts.get(t, 0) + c
    for t, n in sr.NON_INPATIENT_ROOMS[size].items():
        assert counts[t] == n


def test_large_is_sized_for_a_busy_ward_not_an_empty_one():
    beds = sum(c * sr.ROOM_BEDS[t] for _, t, c in _plan('large') if t in sr.INPATIENT_ROOM_TYPES)
    census = 12000 * 0.9 * occ.expected_stay_days(45) / sr.ADMISSION_WINDOW_DAYS
    assert 0.55 <= census / beds <= 0.80


def test_bigger_hospitals_get_more_beds():
    def beds(size):
        return sum(c * sr.ROOM_BEDS[t] for _, t, c in _plan(size) if t in sr.INPATIENT_ROOM_TYPES)
    assert beds('small') <= beds('medium') < beds('large')


# ── allocation ───────────────────────────────────────────────────────────

def _row(i, dept, start, days, cond='Moderate', status='Discharged'):
    dis = start + timedelta(days=days)
    if dis > NOW:
        status, dis = 'Admitted', None
    return {"admission_id": i, "department_id": dept, "admission_date": start, "discharge_date": dis,
            "admission_status": status, "patient_condition": cond, "length_of_stay": days if dis else None,
            "discharge_disposition": 'Home' if dis else 'Still Admitted', "room_id": None, "_planned_days": days}


def _rooms(spec):
    """spec: [(room_id, dept, type)] -> room dicts with the real bed counts."""
    return [{"room_id": rid, "department_id": d, "room_type": t, "bed_capacity": sr.ROOM_BEDS[t]} for rid, d, t in spec]


def test_two_overlapping_stays_never_share_a_one_bed_room():
    rooms = _rooms([("R1", "D1", "Private")])
    rows = [_row(1, "D1", NOW - timedelta(days=20), 5, 'Maximum'),
            _row(2, "D1", NOW - timedelta(days=18), 3, 'Maximum')]
    random.seed(1)
    stats = occ.allocate_rooms(rows, rooms, NOW)
    assert occ.count_overbooked_stays(rows, rooms, NOW) == 0
    second = rows[1]
    # the second patient waited for the bed instead of sharing it: admitted when the first left
    assert second['admission_date'] == rows[0]['discharge_date']
    assert second['discharge_date'] == second['admission_date'] + timedelta(days=3)
    assert stats['waited'] == 1 and stats['cancelled'] == 0


def test_a_two_bed_room_takes_two_patients_at_once_but_not_three():
    rooms = _rooms([("R1", "D1", "Standard")])
    start = NOW - timedelta(days=30)
    rows = [_row(i, "D1", start + timedelta(hours=i), 6, 'Moderate') for i in range(3)]
    random.seed(2)
    occ.allocate_rooms(rows, rooms, NOW)
    assert occ.count_overbooked_stays(rows, rooms, NOW) == 0
    assert rows[0]['admission_date'] < rows[2]['admission_date']
    assert rows[1]['admission_date'] == start + timedelta(hours=1)           # the second bed was free
    assert rows[2]['admission_date'] > start + timedelta(hours=2)             # the third had to wait


def test_waiting_only_ever_moves_an_admission_later_and_keeps_the_stay_length():
    rooms = _rooms([("R1", "D1", "Standard"), ("R2", "D1", "ICU")])
    random.seed(3)
    rows = [_row(i, "D1", NOW - timedelta(days=100) + timedelta(hours=7 * i), random.randint(1, 12),
                 random.choice(['Minimal', 'Moderate', 'Maximum', 'Intensive'])) for i in range(150)]
    before = {r['admission_id']: (r['admission_date'], r['_planned_days']) for r in rows}
    occ.allocate_rooms(rows, rooms, NOW)
    for r in rows:
        if r['room_id']:
            assert r['admission_date'] >= before[r['admission_id']][0]
            if r['discharge_date']:
                assert r['discharge_date'] - r['admission_date'] == timedelta(days=before[r['admission_id']][1])
    assert occ.count_overbooked_stays(rows, rooms, NOW) == 0


def test_a_stay_pushed_past_now_becomes_admitted():
    rooms = _rooms([("R1", "D1", "Private")])
    rows = [_row(1, "D1", NOW - timedelta(days=3), 2, 'Maximum'),            # leaves a day ago
            _row(2, "D1", NOW - timedelta(days=2), 2, 'Maximum')]
    rows[0]['_planned_days'] = 2.9                                            # first stay runs until ~3 hours ago
    rows[0]['discharge_date'] = rows[0]['admission_date'] + timedelta(days=2.9)
    random.seed(4)
    occ.allocate_rooms(rows, rooms, NOW)
    assert rows[1]['room_id'] == "R1" and rows[1]['admission_date'] == rows[0]['discharge_date']
    assert rows[1]['admission_status'] == 'Admitted' and rows[1]['discharge_date'] is None


def test_a_patient_who_waits_too_long_is_placed_at_a_lower_level_of_care():
    rooms = _rooms([("ICU1", "D1", "ICU"), ("S1", "D1", "Standard"), ("P1", "D1", "Private")])
    long_stay = _row(1, "D1", NOW - timedelta(days=40), 38, 'Intensive')       # holds the only ICU bed ~38 days
    arrival = _row(2, "D1", NOW - timedelta(days=30), 5, 'Intensive')
    random.seed(5)
    stats = occ.allocate_rooms([long_stay, arrival], rooms, NOW, max_wait=timedelta(hours=24))
    assert arrival['patient_condition'] == 'Maximum' and arrival['room_id'] == 'P1'   # Private suits Maximum
    assert arrival['admission_date'] == NOW - timedelta(days=30)                      # no waiting at the lower level
    assert stats['lowered'] == 1


def test_a_newborn_never_waits_more_than_a_day_for_a_bed():
    rooms = _rooms([("R1", "D1", "Private")])
    blocker = _row(1, "D1", NOW - timedelta(days=20), 6, 'Maximum')
    baby = _row(2, "D1", NOW - timedelta(days=19), 2, 'Maximum')
    baby['admission_type'] = 'Newborn'
    random.seed(9)
    occ.allocate_rooms([blocker, baby], rooms, NOW)
    assert baby['admission_status'] == 'Cancelled' and baby['room_id'] is None      # would have waited 5 days
    adult = _row(3, "D1", NOW - timedelta(days=19), 2, 'Maximum')
    adult['admission_type'] = 'Emergency'
    random.seed(9)
    occ.allocate_rooms([_row(1, "D1", NOW - timedelta(days=20), 6, 'Maximum'), adult], rooms, NOW)
    assert adult['room_id'] == 'R1' and adult['admission_date'] > NOW - timedelta(days=19)   # an adult just waits


def test_an_admission_with_no_bed_anywhere_in_time_is_cancelled_with_no_room():
    rooms = _rooms([("R1", "D1", "Private")])
    blocker = _row(1, "D1", NOW - timedelta(days=60), 45, 'Maximum')
    victim = _row(2, "D1", NOW - timedelta(days=59), 3, 'Maximum')
    random.seed(6)
    occ.allocate_rooms([blocker, victim], rooms, NOW, max_wait=timedelta(hours=24))
    assert victim['admission_status'] == 'Cancelled' and victim['room_id'] is None
    assert victim['discharge_date'] is None and victim['length_of_stay'] is None


def test_rooms_are_always_in_the_admissions_department_and_suit_the_final_condition():
    random.seed(7)
    plan = occ.plan_rooms(SHARES, 800, 0.9, gen.CONDITION_P, occ.expected_stay_days(45), 'small')
    rooms, n = [], 0
    for dept, rtype, count in plan:
        for _ in range(count):
            n += 1
            rooms.append({"room_id": f"R{n}", "department_id": dept, "room_type": rtype, "bed_capacity": sr.ROOM_BEDS[rtype]})
    by_id = {r['room_id']: r for r in rooms}
    rows = [_row(i, random.choice(IDS), NOW - timedelta(days=random.randint(0, 360), hours=random.randint(0, 23)),
                 random.randint(1, 20), random.choice(gen.CONDITIONS)) for i in range(700)]
    occ.allocate_rooms(rows, rooms, NOW)
    assert occ.count_overbooked_stays(rows, rooms, NOW) == 0
    for r in rows:
        if r['room_id']:
            room = by_id[r['room_id']]
            assert room['department_id'] == r['department_id']
            assert room['room_type'] in sr.CONDITION_ROOM_MAP[r['patient_condition']]
            assert room['room_type'] in sr.INPATIENT_ROOM_TYPES


def test_allocation_is_deterministic_under_a_seed():
    def run():
        random.seed(8)
        rooms = _rooms([("R1", "D1", "Standard"), ("R2", "D1", "Private"), ("R3", "D1", "ICU")])
        rows = [_row(i, "D1", NOW - timedelta(days=60) + timedelta(hours=11 * i), 1 + i % 9,
                     gen.CONDITIONS[i % 4]) for i in range(120)]
        occ.allocate_rooms(rows, rooms, NOW)
        return [(r['room_id'], r['admission_date'], r['patient_condition'], r['admission_status']) for r in rows]
    assert run() == run()


def test_overbooking_counter_detects_a_real_overlap():
    rooms = _rooms([("R1", "D1", "Private")])
    rows = [_row(1, "D1", NOW - timedelta(days=10), 5), _row(2, "D1", NOW - timedelta(days=9), 5)]
    rows[0]['room_id'] = rows[1]['room_id'] = "R1"                           # deliberately double-booked
    assert occ.count_overbooked_stays(rows, rooms, NOW) == 1
