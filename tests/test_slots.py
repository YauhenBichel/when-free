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
