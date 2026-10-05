import datetime as dt

import pytest

from whenfree.messages import dates

TODAY = dt.date(2026, 10, 1)      # a Thursday
D = lambda m, d: dt.date(2026, m, d)

MESSAGE = """When you have a moment, please share your availability for the following dates:
Next week: Wednesday 30th, Thursday 1st, Friday 2nd.
The following week: Monday 5th, Tuesday 6th, Wednesday 7th.
We would appreciate multiple availability options between 10:00am and 4:00pm (UK time).
The interview stage will consist of two technical interviews of 1 hour each."""


def test_a_recruiter_message():
    # "Wednesday 30th" is yesterday, not 30 December: the nearest date that is both a Wednesday and a 30th.
    assert dates.parse_days(MESSAGE, TODAY) == [D(9, 30), D(10, 1), D(10, 2), D(10, 5), D(10, 6), D(10, 7)]
    assert dates.parse_hours(MESSAGE) == (dt.time(10), dt.time(16))


@pytest.mark.parametrize("text, expected", [
    ("Thu 1 Oct, Fri 2 Oct", [D(10, 1), D(10, 2)]),
    ("Thursday the 1st of October or Monday, October 5th", [D(10, 1), D(10, 5)]),
    ("2026-10-05 and 2026-10-06", [D(10, 5), D(10, 6)]),
    ("5 October, 6 Oct.", [D(10, 5), D(10, 6)]),
    ("October 12th works", [D(10, 12)]),
    ("Tues 6", [D(10, 6)]),
])
def test_ways_of_writing_a_date(text, expected):
    assert dates.parse_days(text, TODAY) == expected


@pytest.mark.parametrize("text", [
    "We made 3 decisions in May 2026.",          # not 3 December, and not the 20th of May
    "between 5 and 6 people will join",
    "Monitor 4 shows the sunny 5 day forecast",
])
def test_things_that_are_not_dates(text):
    assert dates.parse_days(text, TODAY) == []


def test_a_time_after_a_weekday_is_not_a_day_of_the_month():
    assert dates.parse_days("Friday 10:30 would suit", TODAY) == [D(10, 2)]     # the coming Friday, not the 10th


@pytest.mark.parametrize("text, expected", [
    ("Are you free tomorrow?", [D(10, 2)]),
    ("today or the day after tomorrow", [D(10, 1), D(10, 3)]),
    ("Thursday or Friday afternoon", [D(10, 1), D(10, 2)]),          # today is Thursday
    ("Would Monday work?", [D(10, 5)]),
    ("this Tuesday", [D(9, 29)]),                                    # already past: the caller names it
    ("next Tuesday", [D(10, 6)]),
    ("this coming Tuesday", [D(10, 6)]),
    ("any time next week", [D(10, 5), D(10, 6), D(10, 7), D(10, 8), D(10, 9)]),
    ("Tuesday or Wednesday next week", [D(10, 6), D(10, 7)]),
    ("the rest of this week", [D(10, 1), D(10, 2)]),
    ("the week after next", [D(10, 12), D(10, 13), D(10, 14), D(10, 15), D(10, 16)]),
])
def test_days_named_relative_to_today(text, expected):
    assert dates.parse_days(text, TODAY) == expected


def test_explicit_dates_win_over_relative_ones():
    # The recruiter's "Next week:" is a heading over explicit dates; it must not add a whole week.
    assert dates.parse_days("Next week: Monday 5th or Tomorrow", TODAY) == [D(10, 5)]


@pytest.mark.parametrize("text", ["The sun is out on Sat", "mondays are busy", "a Fridayish feeling"])
def test_words_that_are_not_relative_days(text):
    assert dates.parse_days(text, TODAY) == []


def test_a_date_early_next_year_is_next_year():
    assert dates.parse_days("Mon 4 Jan", dt.date(2026, 12, 20)) == [dt.date(2027, 1, 4)]


@pytest.mark.parametrize("text, expected", [
    ("between 10:00am and 4:00pm", (10, 0, 16, 0)),
    ("10:00-16:00", (10, 0, 16, 0)),
    ("10:00–4:00", (10, 0, 16, 0)),
    ("9-5pm", (9, 0, 17, 0)),
    ("2 to 4 pm", (14, 0, 16, 0)),
    ("9.30am until 12.30pm", (9, 30, 12, 30)),
    ("from 12pm to 1pm", (12, 0, 13, 0)),
    ("any afternoon", (12, 0, 17, 0)),
    ("Friday morning", (9, 0, 12, 0)),
    ("a morning or an afternoon", (9, 0, 17, 0)),
    ("Good morning! Tuesday evening?", (17, 0, 20, 0)),             # a greeting is not a time of day
    ("between 10 and 3pm, ideally in the afternoon", (10, 0, 15, 0)),  # stated hours win
])
def test_ways_of_writing_hours(text, expected):
    a, b = dates.parse_hours(text)
    assert (a.hour, a.minute, b.hour, b.minute) == expected


def test_no_hours():
    assert dates.parse_hours("any time next week, 5 and 6 October") is None
    assert dates.parse_hours("Good afternoon, are you free?") is None
    with pytest.raises(ValueError):
        dates.hours_from_string("whenever")
