"""Check the settings that silent login needs."""

from django.conf import settings


def get_silent_login_blockers():
    """
    Return the names of the unset settings that silent login needs.

    Logout ends the SSO session only if it sends the stored ID token to the
    OIDC logout endpoint. If logout keeps the SSO session, silent login logs
    the user in again.
    """
    return [
        name
        for name in ("OIDC_OP_LOGOUT_ENDPOINT", "OIDC_STORE_ID_TOKEN")
        if not getattr(settings, name)
    ]
