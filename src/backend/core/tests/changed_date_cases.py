"""Cases for the test of a change to one date of a series.

Each case gives the components of the stored event, the components of
the new event, and the RECURRENCE-ID and previous start that the
updates carry. None means that the updates carry neither. The base
series is the series of the cases for one date.
"""

from core.tests.one_date_cases import (
    ALL_DAY_SERIES,
    LOCAL_SERIES,
    SERIES,
    THIS_AND_FUTURE,
    event,
    gmt1,
    series,
)


def moved(recurrence_id, start, end, **kwargs):
    """Give an entry that moves the date of the RECURRENCE-ID."""
    return event(
        f"RECURRENCE-ID{recurrence_id}", f"DTSTART{start}", f"DTEND{end}", **kwargs
    )


JAN_11 = moved(":20270111T090000Z", ":20270112T100000Z", ":20270112T110000Z")
JAN_18 = moved(":20270118T090000Z", ":20270119T100000Z", ":20270119T110000Z")
STORED_JAN_18 = moved(":20270118T090000Z", ":20270118T140000Z", ":20270118T150000Z")
ANSWERED_JAN_18 = moved(
    ":20270118T090000Z", ":20270118T140000Z", ":20270118T150000Z", answered=True
)
LONGER_JAN_18 = moved(":20270118T090000Z", ":20270118T140000Z", ":20270118T160000Z")
JAN_11_CHANGE = ("20270111T090000Z", "20270111T090000Z")
JAN_18_CHANGE = ("20270118T090000Z", "20270118T140000Z")

CHANGED_DATE_CASES = {
    "new date": ([SERIES], [SERIES, JAN_11], JAN_11_CHANGE),
    "second date": (
        [SERIES, STORED_JAN_18],
        [SERIES, STORED_JAN_18, JAN_11],
        JAN_11_CHANGE,
    ),
    "changed date": ([SERIES, STORED_JAN_18], [SERIES, JAN_18], JAN_18_CHANGE),
    "longer moved date": (
        [SERIES, STORED_JAN_18],
        [SERIES, LONGER_JAN_18],
        JAN_18_CHANGE,
    ),
    "answer on another date": (
        [SERIES, STORED_JAN_18],
        [SERIES, ANSWERED_JAN_18, JAN_11],
        JAN_11_CHANGE,
    ),
    "local time": (
        [gmt1(), LOCAL_SERIES],
        [
            gmt1(),
            LOCAL_SERIES,
            moved(
                ";TZID=Etc/GMT-1:20270111T100000",
                ";TZID=Etc/GMT-1:20270112T100000",
                ";TZID=Etc/GMT-1:20270112T110000",
            ),
        ],
        ("20270111T100000", "20270111T090000Z"),
    ),
    "all day": (
        [ALL_DAY_SERIES],
        [
            ALL_DAY_SERIES,
            moved(
                ";VALUE=DATE:20270111", ";VALUE=DATE:20270112", ";VALUE=DATE:20270113"
            ),
        ],
        ("20270111", "20270111"),
    ),
    "series change": ([SERIES], [series("LOCATION:Room 2"), JAN_11], None),
    "two dates": ([SERIES], [SERIES, JAN_11, JAN_18], None),
    "removed date": ([SERIES, STORED_JAN_18], [SERIES, JAN_11], None),
    "this and future": ([SERIES], [SERIES, THIS_AND_FUTURE], None),
    "stored this and future": (
        [SERIES, THIS_AND_FUTURE],
        [SERIES, THIS_AND_FUTURE, JAN_11],
        None,
    ),
}
