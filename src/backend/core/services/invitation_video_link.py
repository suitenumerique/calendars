"""Video link of an event in the ICS of an outgoing invitation."""

import html
import re
from urllib.parse import urlparse

import icalendar

# The frontend removes this block from the description.
# Keep it in sync with eventDisplayRules.ts.
VIDEO_LINK_MARKER = "-::~ video ~::-"


def _video_url(vevent: icalendar.Event) -> str | None:
    """Return the URL of the event when it is a plain http(s) link."""
    url = str(vevent.get("URL") or "").strip()
    if not url or re.search(r"\s", url):
        return None
    try:
        scheme = urlparse(url).scheme.lower()
    except ValueError:
        return None
    return url if scheme in ("http", "https") else None


def _text(vevent: icalendar.Event, name: str) -> str:
    value = vevent.get(name)
    return str(value) if isinstance(value, icalendar.vText) else ""


def _set_text(vevent: icalendar.Event, name: str, text: str) -> None:
    """Set a text property and keep its parameters."""
    params = getattr(vevent.get(name), "params", {})
    vevent[name] = icalendar.vText(text, params=params)


def _add_to_description(vevent: icalendar.Event, url: str) -> None:
    description = _text(vevent, "DESCRIPTION")
    if url in description:
        return
    block = f"{VIDEO_LINK_MARKER}\n{url}\n{VIDEO_LINK_MARKER}"
    _set_text(
        vevent, "DESCRIPTION", f"{description}\n\n{block}" if description else block
    )


def _add_to_html_description(vevent: icalendar.Event, url: str) -> None:
    """Add the link to X-ALT-DESC. Outlook shows it in place of DESCRIPTION."""
    alt_desc = _text(vevent, "X-ALT-DESC")
    escaped = html.escape(url)
    if not alt_desc or escaped in alt_desc:
        return
    link = f'<p><a href="{escaped}">{escaped}</a></p>'
    head, body_end, tail = alt_desc.rpartition("</body>")
    _set_text(
        vevent,
        "X-ALT-DESC",
        f"{head}{link}{body_end}{tail}" if body_end else f"{alt_desc}{link}",
    )


def _add_conference(vevent: icalendar.Event, url: str) -> None:
    """Add the CONFERENCE property of RFC 7986."""
    if "CONFERENCE" in vevent:
        return
    vevent.add(
        "CONFERENCE",
        icalendar.vUri(url),
        parameters={"VALUE": "URI", "FEATURE": "VIDEO"},
    )


def add_video_link(icalendar_data: str) -> str:
    """Copy the video link of each event from URL to the properties that
    calendar clients show: DESCRIPTION, LOCATION and CONFERENCE.

    Return the data unchanged when no event has an http(s) URL.
    """
    try:
        cal = icalendar.Calendar.from_ical(icalendar_data)
    except (ValueError, TypeError, KeyError):
        return icalendar_data

    changed = False
    for vevent in cal.walk("VEVENT"):
        url = _video_url(vevent)
        if url is None:
            continue
        _add_to_description(vevent, url)
        _add_to_html_description(vevent, url)
        if not _text(vevent, "LOCATION").strip():
            _set_text(vevent, "LOCATION", url)
        _add_conference(vevent, url)
        changed = True

    if not changed:
        return icalendar_data
    return cal.to_ical().decode("utf-8")
