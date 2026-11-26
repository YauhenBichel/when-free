import datetime as dt
import pathlib
from zoneinfo import ZoneInfo

import pytest

from whenfree.core import ical

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


# ---------- calendars that are wrong, or strange ----------

def one(*lines):
    return "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Odd one\r\n" + "\r\n".join(lines) + \
           "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"


START, END = "DTSTART:20261005T100000Z", "DTEND:20261005T110000Z"


@pytest.mark.parametrize("rule", [
    "FREQ=MONTHLY;BYMONTHDAY=0", "FREQ=MONTHLY;BYMONTHDAY=32", "FREQ=MONTHLY;BYMONTHDAY=abc",
    "FREQ=DAILY;INTERVAL=0", "FREQ=DAILY;INTERVAL=-5", "FREQ=DAILY;INTERVAL=abc", "FREQ=YEARLY;INTERVAL=99999999",
    "FREQ=DAILY;COUNT=0", "FREQ=DAILY;COUNT=abc", "FREQ=DAILY;UNTIL=xx", "FREQ=WEEKLY;BYDAY=XX",
    "FREQ=MONTHLY;BYDAY=9MO", "INTERVAL=2",
])
def test_a_rule_with_a_value_that_makes_no_sense_is_refused_not_looped_over(rule):
    ev, = ical.parse(one(START, END, f"RRULE:{rule}"), LONDON)
    with pytest.raises(ical.Unsupported):
        list(ical.expand(ev, at(2026, 10, 1), at(2026, 11, 1)))


@pytest.mark.parametrize("start, rule", [
    ("20260430T100000Z", "FREQ=MONTHLY;INTERVAL=12;BYMONTHDAY=31"),    # April never has a 31st
    ("20260105T100000Z", "FREQ=MONTHLY;INTERVAL=12;BYDAY=5MO"),        # nor has January 2026 a fifth Monday... every 12 months
    ("20240229T100000Z", "FREQ=YEARLY;INTERVAL=4;COUNT=3"),
    ("19000101T100000Z", "FREQ=DAILY;COUNT=99999999"),
])
def test_a_rule_that_names_few_or_no_days_still_ends(start, rule):
    ev, = ical.parse(one(f"DTSTART:{start}", f"DTEND:{start[:9]}110000Z", f"RRULE:{rule}"), LONDON)
    got = list(ical.expand(ev, at(2026, 10, 1), at(2026, 11, 1)))
    assert all(a < at(2026, 11, 1) and b > at(2026, 10, 1) for a, b in got)


def test_a_rule_that_started_long_ago_is_not_walked_day_by_day():
    ev, = ical.parse(one("DTSTART:19000101T100000Z", "DTEND:19000101T110000Z", "RRULE:FREQ=DAILY"), LONDON)
    got = list(ical.expand(ev, at(2026, 10, 5), at(2026, 10, 7)))
    assert [a.astimezone(LONDON).strftime("%d %H:%M") for a, _ in got] == ["05 11:00", "06 11:00"]


@pytest.mark.parametrize("lines, unread", [
    (("DTSTART:garbage", END), "DTSTART"),
    (("DTSTART:20261005T240000Z", END), "DTSTART"),
    (("DTSTART:20261305T100000Z", END), "DTSTART"),
    ((START, "DTEND:nonsense"), "DTEND"),
    ((START, "DURATION:-PT1H"), "DURATION"),
])
def test_an_event_whose_time_cannot_be_read_is_left_out_and_named(lines, unread):
    problems = []
    good = "BEGIN:VEVENT\r\nUID:ok\r\nSUMMARY:Fine\r\nDTSTART:20261006T100000Z\r\nDTEND:20261006T110000Z\r\nEND:VEVENT\r\n"
    text = one(*lines).replace("END:VCALENDAR", good + "END:VCALENDAR")
    events = ical.parse(text, LONDON, problems)
    assert [e.summary for e in events] == ["Fine"]                 # the rest of the calendar still counts
    assert len(problems) == 1 and "'Odd one'" in problems[0] and unread in problems[0]


def test_an_event_that_ends_before_it_starts_is_named():
    problems = []
    assert ical.parse(one(START, "DTEND:20261005T090000Z"), LONDON, problems) == []
    assert "'Odd one'" in problems[0] and "ends before it starts" in problems[0]


@pytest.mark.parametrize("stamp", ["20261005T100000z", "20261005T100000.000Z", "20261005t100000Z"])
def test_times_written_a_little_differently_are_still_read(stamp):
    ev, = ical.parse(one(f"DTSTART:{stamp}", END), LONDON)
    assert ev.start == dt.datetime(2026, 10, 5, 10, tzinfo=dt.timezone.utc)


def test_an_exclusion_that_cannot_be_read_keeps_the_event_and_says_so():
    problems = []
    ev, = ical.parse(one(START, END, "RRULE:FREQ=DAILY", "EXDATE:whenever"), LONDON, problems)
    assert len(list(ical.expand(ev, at(2026, 10, 5), at(2026, 10, 8)))) == 3
    assert "still counted as busy" in problems[0]


def test_an_occurrence_keeps_its_clock_times_when_the_clocks_change():
    # 23:00 to 07:00 every night. On 24-25 October 2026 the night is an hour longer; the event still ends at 07:00.
    ev, = ical.parse(one("DTSTART;TZID=Europe/London:20261020T230000", "DTEND;TZID=Europe/London:20261021T070000",
                         "RRULE:FREQ=DAILY"), LONDON)
    got = {a.strftime("%d"): (a.strftime("%H:%M"), b.strftime("%H:%M"), b - a.astimezone(dt.timezone.utc))
           for a, b in ical.expand(ev, at(2026, 10, 24), at(2026, 10, 26))}
    assert got["24"] == ("23:00", "07:00", dt.timedelta(hours=9))
    assert got["25"] == ("23:00", "07:00", dt.timedelta(hours=8))


def test_the_hour_that_happens_twice_is_not_lost_at_the_edge_of_the_window():
    # 01:30 on 25 October 2026 happens twice in London. An event in the second one (01:30 GMT) is after a window
    # that ends at 01:45 BST, though its clock reading is earlier.
    ev, = ical.parse(one("DTSTART:20261025T013000Z", "DTEND:20261025T020000Z"), LONDON)
    first_0145 = dt.datetime(2026, 10, 25, 1, 45, tzinfo=LONDON)                     # BST: 00:45 UTC
    assert list(ical.expand(ev, at(2026, 10, 25), first_0145)) == []
    assert len(list(ical.expand(ev, at(2026, 10, 25), dt.datetime(2026, 10, 25, 3, tzinfo=LONDON)))) == 1
