"""
Room planning and allocation, so the hospital runs at a realistic occupancy and
no room is ever over capacity.

Before this module, rooms were created at random (random department, random
type) and every admission picked any suitable room with no check that it was
free, so the hospital was nearly empty and, as soon as it got busier, rooms
would have been double-booked. Now:

  plan_rooms      sizes each department's rooms from its expected patient load
                  and the planned occupancy by room type (OCCUPANCY_TARGET), so
                  the wards are busy instead of nearly empty.
  allocate_rooms  places admissions into rooms in date order. A room holds at
                  most its beds at any moment. If no suitable room is free the
                  patient waits for one (up to a week), as patients do, then is
                  placed at a lower level of care; an admission whose bed would
                  only free after "now" is cancelled.

Pure logic with no database access, so it is unit-tested directly. The realised
occupancy is measured from the data (see docs/METHODOLOGY.md), not assumed.
"""

import math
import random
from collections import defaultdict
from datetime import timedelta

from shared_rules import (
    ADMISSION_WINDOW_DAYS, ER_DEPTS, INPATIENT_ROOM_TYPES,
    MAX_BED_WAIT_HOURS, NON_INPATIENT_ROOMS, OB_NEWBORN_DEPTS, OCCUPANCY_SIZING_FACTOR,
    OCCUPANCY_TARGET, OR_DEPTS, ROOM_BEDS, ROOM_ROUTING,
)

CONDITIONS = ['Minimal', 'Moderate', 'Maximum', 'Intensive']

# A newborn is admitted at birth, so it can wait only a day for a bed (the validator expects the
# birth date within three days of the admission)
NEWBORN_MAX_WAIT = timedelta(hours=24)

# Care levels in order, so a patient with no suitable room free can be placed one step down
LOWER_CARE = {
    'Intensive': ['Intensive', 'Maximum', 'Moderate', 'Minimal'],
    'Maximum':   ['Maximum', 'Moderate', 'Minimal'],
    'Moderate':  ['Moderate', 'Minimal'],
    'Minimal':   ['Minimal'],
}

# ROUTING as ordered (type, weight) pairs
ROUTING_ITEMS = {c: list(w.items()) for c, w in ROOM_ROUTING.items()}

# Types every department always has at least one room of: between them they cover every
# care level (ICU for Intensive and Maximum, Standard for Moderate and Minimal)
MIN_ONE_ROOM = ('Standard', 'ICU')


def expected_stay_days(max_stay: int, scale: float = 5.0) -> float:
    """
    Mean length of stay for the generator's draw min(max(1, int(Exp(scale))), max_stay).
    A stay is at least k days with probability exp(-k / scale) for k >= 2, so the
    mean is 1 + sum of that for k = 2..max_stay.
    """
    return 1.0 + sum(math.exp(-k / scale) for k in range(2, max_stay + 1))


def plan_rooms(dept_shares: dict, n_admissions: int, completed_share: float,
               condition_p: list, mean_stay: float, size: str) -> list:
    """
    Decide how many rooms of each type each department gets.

    dept_shares      {department_id: share of admissions}, summing to 1
    n_admissions     admissions generated in the window
    completed_share  share of them that actually happen (not scheduled/cancelled)
    condition_p      probabilities for CONDITIONS, in the same order
    mean_stay        mean length of stay in days
    size             'small' | 'medium' | 'large' (picks the procedure/visit rooms)

    Returns [(department_id, room_type, count)]. Expected beds for a department
    and room type are its patient-days divided by the days in the window and the
    planned occupancy for that type, then rounded to whole rooms. Every
    department gets at least one Standard and one ICU room.
    """
    patient_days = n_admissions * completed_share * mean_stay
    plan = []
    for dept, share in sorted(dept_shares.items()):
        types = [t for t in INPATIENT_ROOM_TYPES if t != 'NICU' or dept in OB_NEWBORN_DEPTS]
        days = defaultdict(float)
        for cond, p_cond in zip(CONDITIONS, condition_p):
            weights = {t: w for t, w in ROOM_ROUTING[cond].items() if t in types}
            total = sum(weights.values())
            for t, w in weights.items():
                days[t] += patient_days * share * p_cond * w / total
        for t in types:
            target = min(0.97, OCCUPANCY_TARGET[t] * OCCUPANCY_SIZING_FACTOR)
            beds = days[t] / (ADMISSION_WINDOW_DAYS * target)
            count = round(beds / ROOM_BEDS[t])
            if t in MIN_ONE_ROOM or (t == 'NICU' and dept in OB_NEWBORN_DEPTS):
                count = max(1, count)
            if count:
                plan.append((dept, t, count))

    # Procedure and visit rooms: they exist but never hold an admission
    extra = NON_INPATIENT_ROOMS[size]
    for room_type, depts in (('ER', ER_DEPTS), ('OR', OR_DEPTS), ('Recovery', OR_DEPTS)):
        for i in range(extra.get(room_type, 0)):
            plan.append((depts[i % len(depts)], room_type, 1))
    return plan


def _fits(stays: list, beds: int, start, end) -> bool:
    """True if one more stay over [start, end) never takes the room past its beds."""
    relevant = [(s, e) for s, e in stays if s < end and e > start]
    if len(relevant) < beds:
        return True
    for x in {start} | {s for s, _ in relevant if s > start}:
        if sum(1 for s, e in relevant if s <= x < e) >= beds:
            return False
    return True


def allocate_rooms(rows: list, rooms: list, now, max_wait=timedelta(hours=MAX_BED_WAIT_HOURS), rng=random) -> dict:
    """
    Assign a room to every admission that took place, in admission-date order.

    rows   admission dicts with admission_id, patient_id, department_id, admission_date,
           discharge_date, admission_status, patient_condition, length_of_stay and
           _planned_days (the stay's length). Changed in place: room_id is set; if
           the patient had to wait for a bed, admission_date moves to when the bed
           freed and the discharge date moves with it (a stay that now runs past
           `now` becomes Admitted); a patient who could not be placed at their care
           level within max_wait is placed at a lower one.
    rooms  dicts with room_id, department_id, room_type, bed_capacity
    now    reference date: a stay not yet over (Admitted) lasts until then

    A patient is never in two beds at once: a stay cannot start before the same patient's
    previous stay ends (it moves to that time), and if the patient is still in hospital now
    a later admission is cancelled.

    A room never holds more patients than it has beds. Order of preference
    (max_wait defaults to MAX_BED_WAIT_HOURS):
      1. a suitable room free at the admission time;
      2. otherwise wait up to max_wait for one to free;
      3. otherwise a free room at the next lower level of care;
      4. otherwise wait up to twice max_wait at the lowest level.
    An admission with no bed by then, or whose bed would only free after `now`, is cancelled.
    Returns counts of what happened.
    """
    by_dept = defaultdict(lambda: defaultdict(list))        # dept -> room_type -> [room_id]
    beds = {}
    for r in rooms:
        if r['room_type'] in INPATIENT_ROOM_TYPES:
            by_dept[r['department_id']][r['room_type']].append(r['room_id'])
            beds[r['room_id']] = r['bed_capacity']
    stays = defaultdict(list)                                # room_id -> [(start, end)]
    patient_free = {}                                        # patient_id -> when their latest stay ends
    latest = now - timedelta(minutes=5)

    def candidates(dept, condition):
        """[(weight, [room_ids])] for the room types this condition is routed to."""
        return [(w, by_dept[dept][t]) for t, w in ROUTING_ITEMS[condition] if by_dept[dept].get(t)]

    def end_of(row, t):
        return now if row['_open'] else t + row['_duration']

    def free_at(dept, condition, t, row):
        """A room free for the whole stay if it starts at t, chosen by routing weight."""
        e = end_of(row, t)
        options = []
        for w, room_ids in candidates(dept, condition):
            free = [rid for rid in room_ids if _fits(stays[rid], beds[rid], t, e)]
            if free:
                options.append((w, free))
        if not options:
            return None
        return rng.choice(rng.choices(options, weights=[w for w, _ in options])[0][1])

    def earliest(dept, condition, start, cap, row):
        """(time, room) of the earliest start >= start (within cap, if given) with a free room."""
        best = None
        for _, room_ids in candidates(dept, condition):
            for rid in room_ids:
                times = [start] + sorted(e for _, e in stays[rid] if e > start)
                for t in times:
                    if (cap is not None and t > start + cap) or t > latest:
                        break
                    if _fits(stays[rid], beds[rid], t, end_of(row, t)):
                        if best is None or t < best[0]:
                            best = (t, [rid])
                        elif t == best[0]:
                            best[1].append(rid)
                        break
        return (best[0], rng.choice(best[1])) if best else None

    stats = {'placed': 0, 'waited': 0, 'wait_hours': 0.0, 'lowered': 0, 'cancelled': 0, 'patient_moved': 0}
    happened = [r for r in rows if r['admission_status'] in ('Admitted', 'Discharged')]
    for row in sorted(happened, key=lambda r: r['admission_date']):
        row['_open'] = row['admission_status'] == 'Admitted' or row['discharge_date'] is None
        row['_duration'] = timedelta(days=row['_planned_days'])
        drawn_start, dept, original = row['admission_date'], row['department_id'], row['patient_condition']
        start = drawn_start
        patient = row.get('patient_id')
        busy_until = patient_free.get(patient) if patient is not None else None
        if busy_until is not None and busy_until > start:      # the patient is still in an earlier stay
            start = busy_until
            stats['patient_moved'] += 1
        wait = min(max_wait, NEWBORN_MAX_WAIT) if row.get('admission_type') == 'Newborn' else max_wait   # a newborn is admitted at birth
        placed = None                                          # (time, room, condition)

        room = free_at(dept, original, start, row)
        if room:
            placed = (start, room, original)
        if not placed:
            hit = earliest(dept, original, start, wait, row)
            if hit:
                placed = (hit[0], hit[1], original)
        if not placed:
            for condition in LOWER_CARE[original][1:]:
                room = free_at(dept, condition, start, row)
                if room:
                    placed = (start, room, condition)
                    break
        if not placed:
            hit = earliest(dept, LOWER_CARE[original][-1], start, 2 * wait, row)
            if hit:
                placed = (hit[0], hit[1], LOWER_CARE[original][-1])

        if not placed or placed[0] > latest:
            row.update(room_id=None, admission_status='Cancelled', discharge_date=None,
                       length_of_stay=None, discharge_disposition='Still Admitted')
            stats['cancelled'] += 1
            continue

        t, room, condition = placed
        if t != start:                                         # waited for a bed
            stats['waited'] += 1
            stats['wait_hours'] += (t - start).total_seconds() / 3600
        if t != drawn_start:                                   # the stay starts later than drawn
            row['admission_date'] = t
            if not row['_open']:
                row['discharge_date'] = t + row['_duration']
                if row['discharge_date'] > now:                # now still in hospital
                    row.update(admission_status='Admitted', discharge_date=None,
                               length_of_stay=None, discharge_disposition='Still Admitted')
                    row['_open'] = True
        stays[room].append((t, end_of(row, t)))
        if patient is not None:
            patient_free[patient] = end_of(row, t)
        row['room_id'] = room
        row['patient_condition'] = condition
        stats['placed'] += 1
        stats['lowered'] += condition != original
    return stats


def count_overbooked_stays(rows: list, rooms: list, now) -> int:
    """
    Count admissions whose room held more patients than it has beds at the moment
    the admission started. Zero means no room was ever over capacity. (An independent
    version of this check lives in the validator as room_double_booked.)
    """
    beds = {r['room_id']: r['bed_capacity'] for r in rooms}
    by_room = defaultdict(list)
    for row in rows:
        if row.get('room_id'):
            by_room[row['room_id']].append((row['admission_date'], row['discharge_date'] or now))
    bad = 0
    for rid, stays in by_room.items():
        for start, _ in stays:
            here = sum(1 for s, e in stays if s <= start < e)
            if here > beds[rid]:
                bad += 1
    return bad
