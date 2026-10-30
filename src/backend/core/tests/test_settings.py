"""
Unit tests for the User model
"""

import pytest

from calendars.settings import Base


def test_invalid_settings_oidc_email_configuration():
    """
    The OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION and OIDC_ALLOW_DUPLICATE_EMAILS settings
    should not be both set to True simultaneously.
    """

    class TestSettings(Base):
        """Fake test settings."""

        OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION = True
        OIDC_ALLOW_DUPLICATE_EMAILS = True

    # The validation is performed during post_setup
    with pytest.raises(ValueError) as excinfo:
        TestSettings().post_setup()

    # Check the exception message
    assert str(excinfo.value) == (
        "Both OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION and "
        "OIDC_ALLOW_DUPLICATE_EMAILS cannot be set to True simultaneously. "
    )


@pytest.mark.parametrize(
    "logout_endpoint, store_id_token, missing",
    [
        (None, True, "OIDC_OP_LOGOUT_ENDPOINT"),
        ("https://oidc.test/logout", False, "OIDC_STORE_ID_TOKEN"),
    ],
)
def test_silent_login_warns_when_logout_keeps_sso(
    caplog, logout_endpoint, store_id_token, missing
):
    """Silent login logs a warning if logout cannot end the SSO session."""

    class TestSettings(Base):
        """Fake test settings."""

        FRONTEND_SILENT_LOGIN_ENABLED = True
        OIDC_OP_LOGOUT_ENDPOINT = logout_endpoint
        OIDC_STORE_ID_TOKEN = store_id_token

    TestSettings().post_setup()

    assert f"settings are not set: {missing}." in caplog.text


@pytest.mark.parametrize(
    "silent_login_enabled, logout_endpoint",
    [(True, "https://oidc.test/logout"), (False, None)],
)
def test_silent_login_no_warning(caplog, silent_login_enabled, logout_endpoint):
    """Silent login logs no warning if it is off or logout ends the SSO session."""

    class TestSettings(Base):
        """Fake test settings."""

        FRONTEND_SILENT_LOGIN_ENABLED = silent_login_enabled
        OIDC_OP_LOGOUT_ENDPOINT = logout_endpoint
        OIDC_STORE_ID_TOKEN = True

    TestSettings().post_setup()

    assert "FRONTEND_SILENT_LOGIN_ENABLED" not in caplog.text
