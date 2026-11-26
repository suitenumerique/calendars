"""Cases for the test of an answer for one date of a series.

Each case gives the components of the stored event, the components of
the new event, and if the attendees get an update. A component is a
list of lines. The base series is weekly, on Mondays from January 4,
2027, 09:00 to 10:00 UTC. The answer is for January 11.
"""

ORGANIZER = "organizer-one-date@example.com"
DECLINING = "declining@external-a.test"
OTHER = "other@external-b.test"
UID = "one-date"

WEEKLY = "RRULE:FREQ=WEEKLY;COUNT=3"
NY = "TZID=America/New_York"
ALARM = [
    "BEGIN:VALARM",
    "TRIGGER:-PT15M",
    "ACTION:DISPLAY",
    'DESCRIPTION;LANGUAGE=fr;ALTREP="cid:a":Rappel',
    "END:VALARM",
]


def event(*lines, answered=False, organizer="CN=Organizer;LANGUAGE=fr", other=""):
    """Give a VEVENT with the organizer and two attendees.

    The lines give the times, the recurrence and the other properties.
    When answered, the first attendee declines.
    """
    declining = "PARTSTAT=DECLINED" if answered else "RSVP=TRUE"
    return [
        "BEGIN:VEVENT",
        f"UID:{UID}",
        *lines,
        "SUMMARY:Weekly event",
        f"ORGANIZER;{organizer}:mailto:{ORGANIZER}",
        f"ATTENDEE;{declining}:mailto:{DECLINING}",
        f"ATTENDEE;RSVP=TRUE{other}:mailto:{OTHER}",
        "END:VEVENT",
    ]


def gmt1(offset="+0100", reordered=False):
    """Give a VTIMEZONE for Etc/GMT-1, which is one hour ahead of UTC."""
    rule = ["DTSTART:19700101T000000", f"TZOFFSETFROM:{offset}", f"TZOFFSETTO:{offset}"]
    if reordered:
        rule.reverse()
    return [
        "BEGIN:VTIMEZONE",
        "TZID:Etc/GMT-1",
        "BEGIN:STANDARD",
        *rule,
        "END:STANDARD",
        "END:VTIMEZONE",
    ]


def calendar(components):
    """Give a VCALENDAR with the components."""
    lines = [line for component in components for line in component]
    return "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Test//EN",
            *lines,
            "END:VCALENDAR",
        ]
    )


SERIES = event("DTSTART:20270104T090000Z", "DTEND:20270104T100000Z", WEEKLY)
ANSWER = event(
    "RECURRENCE-ID:20270111T090000Z",
    "DTSTART:20270111T090000Z",
    "DTEND:20270111T100000Z",
    answered=True,
)


def answer(*lines, **kwargs):
    """Give the answer for January 11 with other times or properties."""
    return event("RECURRENCE-ID:20270111T090000Z", *lines, answered=True, **kwargs)


def series(*lines):
    """Give the base series with more lines."""
    return event("DTSTART:20270104T090000Z", "DTEND:20270104T100000Z", WEEKLY, *lines)


def rule_case(rule, start, answer_start):
    """Give a case for a series with another rule, in UTC.

    The answer is for a date that the rule does not give, or that
    EventIterator does not give correctly.
    """
    return (
        [event(f"DTSTART:{start}Z", f"RRULE:{rule}")],
        [
            event(f"DTSTART:{start}Z", f"RRULE:{rule}"),
            event(
                f"RECURRENCE-ID:{answer_start}Z",
                f"DTSTART:{answer_start}Z",
                answered=True,
            ),
        ],
        True,
    )


# The first date moves to the start of the second date. The series
# excludes the second date.
MOVED_SERIES = series("EXDATE:20270111T090000Z")
MOVED_DATE = event(
    "RECURRENCE-ID:20270104T090000Z",
    "DTSTART:20270111T090000Z",
    "DTEND:20270111T100000Z",
)

# The first date and the later dates move one hour later.
THIS_AND_FUTURE = event(
    "RECURRENCE-ID;RANGE=THISANDFUTURE:20270104T090000Z",
    "DTSTART:20270104T100000Z",
    "DTEND:20270104T110000Z",
)

# The series is in Etc/GMT-1 time, the answer is in UTC.
LOCAL_SERIES = event(
    "DTSTART;TZID=Etc/GMT-1:20270104T100000",
    "DTEND;TZID=Etc/GMT-1:20270104T110000",
    WEEKLY,
)

# The series is in New York time, and the second date crosses the change
# to summer time, on March 14, 2027. It lasts 24 hours, so it ends at
# 13:00 in New York, which is 17:00 UTC.
DST_SERIES = event(
    f"DTSTART;{NY}:20270306T120000", f"DTEND;{NY}:20270307T120000", WEEKLY
)

# 02:30 does not exist in New York on March 14, 2027. RFC 5545 uses the
# offset before the change, so the date starts at 03:30 in summer time.
GAP_SERIES = event(
    f"DTSTART;{NY}:20270307T023000", f"DTEND;{NY}:20270307T033000", WEEKLY
)

# The first date lasts 23 hours, and the later dates last 24 hours.
DAY_SERIES = event(f"DTSTART;{NY}:20270313T120000", "DURATION:P1D", WEEKLY)

ALL_DAY_SERIES = event(
    "DTSTART;VALUE=DATE:20270104", "DTEND;VALUE=DATE:20270105", WEEKLY
)

ONE_DATE_CASES = {
    # The answer only, written in the same way or in another way.
    "answer": ([SERIES], [SERIES, ANSWER], False),
    "reordered parameters": (
        [SERIES],
        [
            event(
                "DTSTART:20270104T090000Z",
                "DTEND:20270104T100000Z",
                WEEKLY,
                organizer="LANGUAGE=fr;CN=Organizer",
            ),
            answer(
                "DTSTART:20270111T090000Z",
                "DTEND:20270111T100000Z",
                organizer="LANGUAGE=fr;CN=Organizer",
            ),
        ],
        False,
    ),
    "no end": (
        [event("DTSTART:20270104T090000Z", WEEKLY)],
        [event("DTSTART:20270104T090000Z", WEEKLY), answer("DTSTART:20270111T090000Z")],
        False,
    ),
    "duration": (
        [event("DTSTART:20270104T090000Z", "DURATION:PT1H", WEEKLY)],
        [
            event("DTSTART:20270104T090000Z", "DURATION:PT1H", WEEKLY),
            answer("DTSTART:20270111T090000Z", "DURATION:PT1H"),
        ],
        False,
    ),
    "same timezone": (
        [gmt1(), LOCAL_SERIES],
        [gmt1(), LOCAL_SERIES, ANSWER],
        False,
    ),
    "reordered timezone": (
        [gmt1(), LOCAL_SERIES],
        [gmt1(reordered=True), LOCAL_SERIES, ANSWER],
        False,
    ),
    "daylight saving": (
        [DAY_SERIES],
        [
            DAY_SERIES,
            event(
                f"RECURRENCE-ID;{NY}:20270320T120000",
                f"DTSTART;{NY}:20270320T120000",
                "DURATION:P1D",
                answered=True,
            ),
        ],
        False,
    ),
    "daylight saving end": (
        [DST_SERIES],
        [
            DST_SERIES,
            event(
                f"RECURRENCE-ID;{NY}:20270313T120000",
                f"DTSTART;{NY}:20270313T120000",
                "DTEND:20270314T170000Z",
                answered=True,
            ),
        ],
        False,
    ),
    "daylight saving gap": (
        [GAP_SERIES],
        [
            GAP_SERIES,
            event(
                f"RECURRENCE-ID;{NY}:20270314T033000",
                f"DTSTART;{NY}:20270314T033000",
                f"DTEND;{NY}:20270314T043000",
                answered=True,
            ),
        ],
        False,
    ),
    "reordered alarm": (
        [series(*ALARM)],
        [
            series(*ALARM),
            answer(
                "DTSTART:20270111T090000Z",
                "DTEND:20270111T100000Z",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                'DESCRIPTION;ALTREP="cid:a";LANGUAGE=fr:Rappel',
                "TRIGGER:-PT15M",
                "END:VALARM",
            ),
        ],
        False,
    ),
    "email case": (
        [SERIES],
        [
            SERIES,
            [
                line.replace(f"mailto:{OTHER}", f"MAILTO:{OTHER.capitalize()}")
                for line in ANSWER
            ],
        ],
        False,
    ),
    # A real change on the answered date.
    "move": (
        [SERIES],
        [SERIES, answer("DTSTART:20270111T100000Z", "DTEND:20270111T110000Z")],
        True,
    ),
    "earlier start": (
        [SERIES],
        [SERIES, answer("DTSTART:20270111T083000Z", "DTEND:20270111T100000Z")],
        True,
    ),
    "longer": (
        [SERIES],
        [SERIES, answer("DTSTART:20270111T090000Z", "DTEND:20270111T103000Z")],
        True,
    ),
    "daylight saving shorter": (
        [DST_SERIES],
        [
            DST_SERIES,
            event(
                f"RECURRENCE-ID;{NY}:20270313T120000",
                f"DTSTART;{NY}:20270313T120000",
                "DTEND:20270314T160000Z",
                answered=True,
            ),
        ],
        True,
    ),
    "all day": (
        [ALL_DAY_SERIES],
        [
            ALL_DAY_SERIES,
            event(
                "RECURRENCE-ID;VALUE=DATE:20270111",
                "DTSTART:20270111T000000",
                "DTEND:20270112T000000",
                answered=True,
            ),
        ],
        True,
    ),
    "floating": (
        [event("DTSTART:20270104T090000", "DTEND:20270104T100000", WEEKLY)],
        [event("DTSTART:20270104T090000", "DTEND:20270104T100000", WEEKLY), ANSWER],
        True,
    ),
    "floating end": (
        [SERIES],
        [SERIES, answer("DTSTART:20270111T090000Z", "DTEND:20270111T100000")],
        True,
    ),
    "timezone": (
        [gmt1(), LOCAL_SERIES],
        [gmt1(offset="+0200"), LOCAL_SERIES, ANSWER],
        True,
    ),
    "location": (
        [SERIES],
        [
            SERIES,
            answer(
                "DTSTART:20270111T090000Z", "DTEND:20270111T100000Z", "LOCATION:Room B"
            ),
        ],
        True,
    ),
    "series location": (
        [SERIES],
        [
            series("LOCATION:Room C"),
            answer(
                "DTSTART:20270111T090000Z", "DTEND:20270111T100000Z", "LOCATION:Room C"
            ),
        ],
        True,
    ),
    "role": (
        [SERIES],
        [
            SERIES,
            answer(
                "DTSTART:20270111T090000Z",
                "DTEND:20270111T100000Z",
                other=";ROLE=OPT-PARTICIPANT",
            ),
        ],
        True,
    ),
    "forced": (
        [SERIES],
        [
            SERIES,
            answer(
                "DTSTART:20270111T090000Z",
                "DTEND:20270111T100000Z",
                other=";SCHEDULE-FORCE-SEND=REQUEST",
            ),
        ],
        True,
    ),
    "alarm": (
        [series(*ALARM)],
        [
            series(*ALARM),
            answer(
                "DTSTART:20270111T090000Z",
                "DTEND:20270111T100000Z",
                *[line.replace("-PT15M", "-PT30M") for line in ALARM],
            ),
        ],
        True,
    ),
    # A date that is not a regular date of the series.
    "moved date": (
        [MOVED_SERIES, MOVED_DATE],
        [MOVED_SERIES, MOVED_DATE, ANSWER],
        True,
    ),
    "no master": ([MOVED_DATE], [MOVED_DATE, ANSWER], True),
    "this and future": (
        [SERIES],
        [
            SERIES,
            event(
                "RECURRENCE-ID;RANGE=THISANDFUTURE:20270111T090000Z",
                "DTSTART:20270111T090000Z",
                "DTEND:20270111T100000Z",
                answered=True,
            ),
        ],
        True,
    ),
    "stored this and future": (
        [SERIES, THIS_AND_FUTURE],
        [SERIES, THIS_AND_FUTURE, ANSWER],
        True,
    ),
    "dropped date": (
        [
            SERIES,
            event(
                "RECURRENCE-ID:20270118T090000Z",
                "DTSTART:20270118T090000Z",
                "DTEND:20270118T100000Z",
                "LOCATION:Room D",
            ),
        ],
        [SERIES, ANSWER],
        True,
    ),
    # A series that EventIterator does not handle well.
    # The extra date is in Paris time. EventIterator reads it in UTC.
    "rdate": (
        [series("RDATE;TZID=Europe/Paris:20270107T090000")],
        [
            series("RDATE;TZID=Europe/Paris:20270107T090000"),
            event(
                "RECURRENCE-ID:20270107T090000Z",
                "DTSTART:20270107T090000Z",
                "DTEND:20270107T100000Z",
                answered=True,
            ),
        ],
        True,
    ),
    # The rule excludes the first and the second dates.
    "exrule": (
        [series("EXRULE:FREQ=DAILY;COUNT=9")],
        [series("EXRULE:FREQ=DAILY;COUNT=9"), ANSWER],
        True,
    ),
    "no rrule": (
        [event("DTSTART:20270104T090000Z", "DTEND:20270104T100000Z")],
        [
            event("DTSTART:20270104T090000Z", "DTEND:20270104T100000Z"),
            event(
                "RECURRENCE-ID:20270104T090000Z",
                "DTSTART:20270104T090000Z",
                "DTEND:20270104T100000Z",
                answered=True,
            ),
        ],
        True,
    ),
    # EventIterator ignores BYMONTH, so it adds February 1.
    "unsupported rule": rule_case(
        "FREQ=DAILY;BYMONTH=1;COUNT=3", "20270131T090000", "20270201T090000"
    ),
    # EventIterator adds March 1, 2029.
    "unsupported yearly rule": rule_case(
        "FREQ=YEARLY;BYMONTH=2;COUNT=3", "20280229T090000", "20290301T090000"
    ),
    # EventIterator adds the UNTIL date.
    "until date": rule_case(
        "FREQ=MONTHLY;BYMONTHDAY=15;UNTIL=20270201T090000Z",
        "20270115T090000",
        "20270201T090000",
    ),
    "set position": rule_case(
        "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1;UNTIL=20270201T090000Z",
        "20270129T090000",
        "20270201T090000",
    ),
}
