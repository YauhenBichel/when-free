import datetime as dt
import pathlib
from zoneinfo import ZoneInfo

import pytest

from whenfree import ical

LONDON = ZoneInfo("Europe/London")
SAMPLE = (pathlib.Path(__file__).parent / "data" / "sample.ics").read_text()


def at(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=LONDON)


def by_uid(uid):
    return [e for e in ical.parse(SAMPLE, LONDON) if e.uid == uid]


def test_reads_every_event_and_skips_nested_alarms():
    events = ical.parse(SAMPLE, LONDON)
    assert len(events) == 13
    call = by_uid("a7")[0]
    assert call.summary == "Recruiter call, with a comma"      # the VALARM's DESCRIPTION did not replace anything
    assert call.end - call.start == dt.timedelta(minutes=30)


def test_times_keep_their_zone():
    utc_call = by_uid("a2")[0]
    assert utc_call.start.astimezone(LONDON) == at(2026, 10, 2, 14)     # 13:00Z is 14:00 in British Summer Time
    assert by_uid("a1")[0].start == at(2026, 10, 1, 11)


def test_flags():
    assert by_uid("a4")[0].all_day and by_uid("a4")[0].transparent
    assert by_uid("a6")[0].cancelled
    assert not by_uid("a12")[0].transparent
    # a colon inside a quoted parameter is not the end of the property name
    assert ("mailto:me@example.com", "DECLINED") in by_uid("a5")[0].attendees


def starts(event, a, b):
    return [s for s, _ in ical.expand(event, a, b)]


def test_weekly_rule_with_an_excluded_date():
    standup = by_uid("a3")[0]
    got = starts(standup, at(2026, 10, 1), at(2026, 10, 10))
    assert got == [at(2026, 10, 2, 9, 30), at(2026, 10, 7, 9, 30), at(2026, 10, 9, 9, 30)]   # Mon 5 Oct is excluded


def test_count_and_until_end_a_series():
    assert starts(by_uid("a9")[0], at(2026, 9, 28), at(2026, 10, 10)) == [
        at(2026, 9, 28, 13), at(2026, 9, 29, 13), at(2026, 9, 30, 13)]
    assert starts(by_uid("a10")[0], at(2026, 10, 1), at(2026, 10, 31)) == []


def test_first_monday_of_the_month():
    review = by_uid("a8")[0]
    assert starts(review, at(2026, 10, 1), at(2026, 12, 31)) == [
        at(2026, 10, 5, 15), at(2026, 11, 2, 15), at(2026, 12, 7, 15)]


def test_wall_clock_time_survives_the_end_of_summer_time():
    standup = by_uid("a3")[0]
    after = starts(standup, at(2026, 10, 26), at(2026, 10, 27))      # clocks went back on 25 October 2026
    assert after == [at(2026, 10, 26, 9, 30)]
    assert after[0].utcoffset() == dt.timedelta(0)


def test_a_rule_that_is_not_expanded_says_so():
    odd = ical.Event(start=at(2026, 9, 1, 9), end=at(2026, 9, 1, 10),
                     rrule={"FREQ": "MONTHLY", "BYDAY": "MO,TU,WE,TH,FR", "BYSETPOS": "-1"})
    with pytest.raises(ical.Unsupported):
        list(ical.expand(odd, at(2026, 10, 1), at(2026, 10, 31)))


def test_an_old_daily_series_is_reached_without_walking_every_day():
    old = ical.Event(start=at(2011, 1, 3, 8), end=at(2011, 1, 3, 9), rrule={"FREQ": "DAILY", "INTERVAL": "2"})
    got = starts(old, at(2026, 10, 1), at(2026, 10, 4))
    assert [g.day for g in got] in ([1, 3], [2])        # every second day, whichever parity 2011-01-03 gives
    assert all((g.date() - dt.date(2011, 1, 3)).days % 2 == 0 for g in got)
