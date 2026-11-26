import datetime as dt
import pathlib
from zoneinfo import ZoneInfo

from whenfree.core import ical, slots

LONDON = ZoneInfo("Europe/London")
EVENTS = ical.parse((pathlib.Path(__file__).parent / "data" / "sample.ics").read_text(), LONDON)
OPENS, CLOSES = dt.time(10), dt.time(16)


def busy(all_day_busy=False, me=("me@example.com",), warnings=None):
    a = dt.datetime(2026, 10, 1, tzinfo=LONDON)
    b = dt.datetime(2026, 10, 10, tzinfo=LONDON)
    return slots.busy_blocks(EVENTS, a, b, me=list(me), all_day_busy=all_day_busy, warnings=warnings)


def free(day, **kw):
    got = slots.free_slots(dt.date(2026, 10, day), OPENS, CLOSES, kw.pop("blocks", None) or busy(), LONDON, **kw)
    return [(a.strftime("%H:%M"), b.strftime("%H:%M")) for a, b in got]


def test_a_buffer_is_kept_around_events_and_short_gaps_are_dropped():
    # Dentist 11:00-12:00. 10:00-10:45 is shorter than an hour, so only the afternoon is offered.
    assert free(1) == [("12:15", "16:00")]


def test_an_event_stored_in_utc_is_answered_in_local_time():
    # Standup ends 10:00; the call is 13:00Z, which is 14:00 in London. The gap after it is 45 minutes.
    assert free(2) == [("10:15", "13:45")]


def test_excluded_dates_and_monthly_rules():
    # No standup on Mon 5 Oct (EXDATE). The first-Monday review is 15:00-16:00.
    assert free(5) == [("10:00", "14:45")]


def test_declined_free_and_moved_events():
    # Tue 6 Oct: a declined invitation and a "Free" birthday do not block. The weekly one-to-one was moved
    # from 11:00 to 15:00 on this date only, so 11:00 is free and 15:00 is not.
    assert free(6) == [("10:00", "14:45")]


def test_a_declined_invitation_blocks_when_it_is_not_mine():
    blocks = busy(me=())
    assert free(6, blocks=blocks) == [("10:00", "13:45")]


def test_cancelled_events_do_not_block():
    assert free(7) == [("10:15", "12:00"), ("13:00", "16:00")]


def test_whole_day_events_block_only_when_asked():
    assert free(8) == [("10:00", "16:00")]
    assert free(8, blocks=busy(all_day_busy=True)) == []


def test_today_starts_at_the_next_quarter_hour_and_is_rechecked_for_length():
    assert free(1, now=dt.datetime(2026, 10, 1, 13, 7, tzinfo=LONDON)) == [("13:15", "16:00")]
    assert free(1, now=dt.datetime(2026, 10, 1, 15, 20, tzinfo=LONDON)) == []      # 30 minutes left: too short
    assert free(1, now=dt.datetime(2026, 10, 1, 18, 0, tzinfo=LONDON)) == []


def test_min_and_buffer_are_adjustable():
    assert free(1, min_minutes=30) == [("10:00", "10:45"), ("12:15", "16:00")]
    assert free(1, buffer_minutes=0) == [("10:00", "11:00"), ("12:00", "16:00")]


def test_an_unexpandable_rule_blocks_its_first_date_and_warns():
    odd = ical.Event(start=dt.datetime(2026, 10, 1, 14, tzinfo=LONDON), end=dt.datetime(2026, 10, 1, 15, tzinfo=LONDON),
                     summary="Odd", rrule={"FREQ": "MONTHLY", "BYSETPOS": "-1", "BYDAY": "FR"})
    warnings = []
    blocks = slots.busy_blocks([odd], dt.datetime(2026, 10, 1, tzinfo=LONDON), dt.datetime(2026, 10, 2, tzinfo=LONDON),
                               warnings=warnings)
    assert len(blocks) == 1 and "Odd" in warnings[0]


# ---------- the days the clocks change ----------

UTC = dt.timezone.utc
LA = ZoneInfo("America/Los_Angeles")


def block(start, end):
    return slots.Busy(start, end, "x")


def test_an_event_in_another_zone_is_placed_by_real_time_on_a_changeover_day():
    # 01:05-02:00 UTC on 29 March is 18:05-19:00 the evening before in Los Angeles. The UTC value and the same
    # moment written in London time must give the same answer.
    a, b = dt.datetime(2026, 3, 29, 1, 5, tzinfo=UTC), dt.datetime(2026, 3, 29, 2, 0, tzinfo=UTC)
    for busy_ in ([block(a, b)], [block(a.astimezone(LONDON), b.astimezone(LONDON))]):
        got = slots.free_slots(dt.date(2026, 3, 28), dt.time(17), dt.time(22), busy_, LA, buffer_minutes=15, min_minutes=15)
        assert [(x.strftime("%H:%M"), y.strftime("%H:%M")) for x, y in got] == [("17:00", "17:50"), ("19:15", "22:00")]


def test_free_time_never_overlaps_busy_time_on_days_the_clocks_change():
    # A property, tried on many cases: whatever zone the busy blocks are written in, a slot is inside the hours,
    # at least the minimum long in real time, and the buffer away from every block.
    import random
    rnd = random.Random(20261126)
    days = {"Europe/London": [dt.date(2026, 3, 29), dt.date(2026, 10, 25)],
            "America/New_York": [dt.date(2026, 3, 8), dt.date(2026, 11, 1)],
            "Australia/Lord_Howe": [dt.date(2026, 4, 5), dt.date(2026, 10, 4)]}      # Lord Howe moves by half an hour
    zones = [ZoneInfo(z) for z in days] + [UTC]
    for _ in range(400):
        name = rnd.choice(list(days))
        tz, day = ZoneInfo(name), rnd.choice(days[name])
        opens, closes = dt.time(rnd.choice([0, 1, 2, 3, 9])), dt.time(rnd.choice([4, 12, 18, 23]), 30)
        base = dt.datetime.combine(day, dt.time(0), UTC) - dt.timedelta(hours=14)
        blocks = []
        for _ in range(rnd.choice([1, 3, 10])):
            start = base + dt.timedelta(minutes=rnd.randint(0, 40 * 60))
            end = start + dt.timedelta(minutes=rnd.choice([5, 30, 90, 600]))
            zone = rnd.choice(zones)
            blocks.append(block(start.astimezone(zone), end.astimezone(zone)))
        pad, need = dt.timedelta(minutes=rnd.choice([0, 15])), rnd.choice([15, 60])
        lo = dt.datetime.combine(day, opens, tz).astimezone(UTC)
        hi = dt.datetime.combine(day, closes, tz).astimezone(UTC)
        got = [(a.astimezone(UTC), b.astimezone(UTC)) for a, b in slots.free_slots(
            day, opens, closes, blocks, tz, buffer_minutes=pad // dt.timedelta(minutes=1), min_minutes=need)]
        case = (name, day, opens, closes)
        for a, b in got:
            assert lo <= a and b <= hi and b - a >= dt.timedelta(minutes=need), case
            for k in blocks:
                assert b <= k.start.astimezone(UTC) - pad or a >= k.end.astimezone(UTC) + pad, case
        # and nothing was held back: every minute in the hours is in a slot, near a block, or in a gap too short
        covered = sorted(got + [(max(lo, k.start.astimezone(UTC) - pad), min(hi, k.end.astimezone(UTC) + pad))
                                for k in blocks if k.start.astimezone(UTC) - pad < hi and k.end.astimezone(UTC) + pad > lo])
        cursor = lo
        for a, b in covered:
            assert a - cursor < dt.timedelta(minutes=need), case
            cursor = max(cursor, b)
        assert hi - cursor < dt.timedelta(minutes=need), case


def test_hours_that_do_not_exist_that_day_start_when_the_clocks_land():
    # 29 March 2026 in London: 01:00 jumps to 02:00, so "from 01:30" is 02:30, and nothing is offered twice.
    got = slots.free_slots(dt.date(2026, 3, 29), dt.time(1, 30), dt.time(5), [], LONDON, min_minutes=30)
    assert [(a.strftime("%H:%M"), b.strftime("%H:%M"), b - a) for a, b in got] == [("02:30", "05:00", dt.timedelta(hours=2, minutes=30))]


def test_a_now_with_seconds_starts_at_the_next_quarter_hour_not_the_one_just_gone():
    now = dt.datetime(2026, 10, 6, 10, 15, 1, tzinfo=LONDON)
    got = slots.free_slots(dt.date(2026, 10, 6), OPENS, CLOSES, [], LONDON, now=now)
    assert got[0][0].strftime("%H:%M") == "10:30"
    on_the_dot = slots.free_slots(dt.date(2026, 10, 6), OPENS, CLOSES, [], LONDON, now=now.replace(second=0))
    assert on_the_dot[0][0].strftime("%H:%M") == "10:15"


def test_an_index_gives_the_same_answer_as_reading_every_block():
    blocks = busy()
    timeline = slots.Timeline(blocks)
    for day in range(1, 10):
        d = dt.date(2026, 10, day)
        assert slots.free_slots(d, OPENS, CLOSES, timeline, LONDON) == slots.free_slots(d, OPENS, CLOSES, blocks, LONDON)
    a, b = dt.datetime(2026, 10, 1, tzinfo=LONDON), dt.datetime(2026, 10, 2, tzinfo=LONDON)
    assert timeline.overlapping(a, b) == [k for k in blocks if k.start < b and k.end > a]
