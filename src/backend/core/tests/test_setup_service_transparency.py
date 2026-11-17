"""Tests for the transparency of the mailbox calendar instances."""

from unittest import mock

from django.test import override_settings

import pytest

from core import factories
from core.services.setup_service import SetupService, _starts_transparent

pytestmark = pytest.mark.django_db

PERSON = {"email": "bob@example.com", "is_identity": True}


@pytest.mark.parametrize(
    ("user_email", "mailbox", "transparent"),
    [
        ("alice@example.com", PERSON, True),
        ("Bob@Example.com", PERSON, False),
        (
            "alice@example.com",
            {"email": "team@example.com", "is_identity": False},
            False,
        ),
        (
            "alice@example.com",
            {"email": "a.smith@example.com", "is_identity": False},
            False,
        ),
        ("alice@example.com", {"email": "team@example.com"}, False),
    ],
    ids=["delegate", "owner", "team", "alias", "missing-field"],
)
def test_starts_transparent(user_email, mailbox, transparent):
    """Only a delegate of a person's mailbox starts transparent.

    A team mailbox and an alias of a person both have ``is_identity``
    False. Calendars cannot tell them apart, so both start opaque.
    """
    assert _starts_transparent(user_email, mailbox) is transparent


def _service():
    with mock.patch("core.services.setup_service.CalDAVHTTPClient") as mock_http:
        service = SetupService()
    service._messages = mock.MagicMock()  # pylint: disable=protected-access
    request = mock_http.return_value.internal_request
    request.return_value = mock.Mock(
        status_code=200, json=mock.Mock(return_value={"active": []})
    )
    return service, request


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_user_sync_sends_the_transparency():
    """Each share of the user sync tells if the instance starts transparent."""
    service, request = _service()
    service.messages.get_user_mailboxes.return_value = [
        {**PERSON, "role": "viewer"},
        {"email": "alice@example.com", "role": "admin", "is_identity": True},
    ]

    service.sync_user_mailboxes(factories.UserFactory(email="alice@example.com"))

    shares = request.call_args.kwargs["json"]["shares"]
    assert [share["transparent"] for share in shares] == [True, False]


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_mailbox_setup_sends_the_transparency():
    """The creator instance and the fan-out use the mailbox data.

    Alice is a delegate of the mailbox of Bob.
    """
    service, request = _service()
    user = factories.UserFactory(email="alice@example.com")
    mailbox = {
        **PERSON,
        "role": "sender",
        "users": [{"email": user.email, "role": "sender"}],
    }
    request.side_effect = [
        mock.Mock(status_code=201, json=mock.Mock(return_value={})),
        mock.Mock(status_code=200, json=mock.Mock(return_value={"active": []})),
    ]

    with (
        mock.patch.object(service, "_get_user_mailbox", return_value=mailbox),
        mock.patch(
            "core.services.setup_service._resolve_mailbox_org_id",
            return_value="org-id",
        ),
    ):
        service.setup(user, "Bob", mailbox_email=PERSON["email"])

    create, sync = request.call_args_list
    assert create.kwargs["json"]["caller_transparent"] is True
    assert sync.kwargs["json"]["shares"][0]["transparent"] is True
