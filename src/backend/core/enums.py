"""Channel enums and scope-to-method mappings."""

from enum import StrEnum


class ChannelScopeLevel(StrEnum):
    """Scope level for a Channel: which resource the channel is bound to.

    Mirrors suitenumerique/messages ChannelScopeLevel.
    ``StrEnum`` (not ``TextChoices``): the field is a free-form CharField
    so adding a new scope level never requires a migration.

    - GLOBAL: instance-wide, no target. Creatable only via Django admin or CLI.
    - USER: bound to one User; actions limited to that user's calendars.
    - CALENDAR: bound to one CalDAV path; actions limited to that calendar.
    """

    GLOBAL = "global"
    USER = "user"
    CALENDAR = "calendar"


class ChannelScope(StrEnum):
    """Capability scopes granted to a Channel.

    Mirrors suitenumerique/messages ChannelApiKeyScope. ``StrEnum`` (not
    ``TextChoices``): Channel.settings["scopes"] is a free-form JSON list
    so adding a new scope never requires a migration. Members ARE strings
    (``ChannelScope.CALENDARS_READ == "calendars:read"``) so comparisons,
    dict keys and ORM filters work transparently.

    Each scope maps to a set of CalDAV HTTP methods that can be enforced
    at protocol level (path + method) without deep XML/iCal inspection.
    """

    CALENDARS_READ = "calendars:read"
    EVENTS_READ = "events:read"
    EVENTS_WRITE = "events:write"
    CALENDARS_WRITE = "calendars:write"


CHANNEL_SCOPE_COLLECTION_METHODS = {
    ChannelScope.CALENDARS_READ: frozenset({"PROPFIND", "OPTIONS"}),
    ChannelScope.CALENDARS_WRITE: frozenset(
        {"MKCALENDAR", "MKCOL", "PROPPATCH", "DELETE"}
    ),
    # REPORT against a calendar collection (path ending with `/`) is
    # how CalDAV clients fetch events: calendar-query,
    # calendar-multiget, sync-collection. It's read-only, so it
    # belongs to events:read even though the path is a collection.
    ChannelScope.EVENTS_READ: frozenset({"REPORT"}),
}

CHANNEL_SCOPE_OBJECT_METHODS = {
    ChannelScope.EVENTS_READ: frozenset({"GET", "REPORT", "OPTIONS"}),
    ChannelScope.EVENTS_WRITE: frozenset({"PUT", "DELETE", "POST"}),
}
