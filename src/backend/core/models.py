"""
Declare and configure the models for the calendars core application
"""

import base64
import secrets
import uuid
from logging import getLogger

from django.conf import settings
from django.contrib.auth import models as auth_models
from django.contrib.auth.base_user import AbstractBaseUser
from django.core import mail, validators
from django.db import models

from encrypted_fields.fields import EncryptedJSONField
from timezone_field import TimeZoneField

logger = getLogger(__name__)


class DuplicateEmailError(Exception):
    """Raised when an email is already associated with a pre-existing user."""

    def __init__(self, message=None, email=None):
        """Set message and email to describe the exception."""
        self.message = message
        self.email = email
        super().__init__(self.message)


class BaseModel(models.Model):
    """
    Serves as an abstract base model for other models, ensuring that records are validated
    before saving as Django doesn't do it by default.

    Includes fields common to all models: a UUID primary key and creation/update timestamps.
    """

    id = models.UUIDField(
        verbose_name="id",
        help_text="primary key for the record as UUID",
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(
        verbose_name="created on",
        help_text="date and time at which a record was created",
        auto_now_add=True,
        editable=False,
    )
    updated_at = models.DateTimeField(
        verbose_name="updated on",
        help_text="date and time at which a record was last updated",
        auto_now=True,
        editable=False,
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Call `full_clean` before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class SharingLevel(models.TextChoices):
    """Calendar sharing visibility levels within an organization."""

    NONE = "none", "No sharing"
    FREEBUSY = "freebusy", "Free/Busy only"
    READ = "read", "Read access"
    WRITE = "write", "Read/Write access"


class Organization(BaseModel):
    """Organization model, populated from OIDC claims and entitlements.

    Every user belongs to exactly one organization, determined by their
    email domain (default) or a configurable OIDC claim. Orgs are
    created automatically on first login.
    """

    name = models.CharField(max_length=200, blank=True, default="")
    external_id = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        help_text="Organization identifier from OIDC claim or email domain.",
    )
    default_sharing_level = models.CharField(
        max_length=10,
        choices=SharingLevel.choices,
        null=True,
        blank=True,
        help_text=(
            "Default calendar sharing level for org members. "
            "Null means use the server-wide default (ORG_DEFAULT_SHARING_LEVEL)."
        ),
    )

    class Meta:
        db_table = "calendars_organization"
        verbose_name = "organization"
        verbose_name_plural = "organizations"

    def __str__(self):
        return self.name or self.external_id

    @property
    def effective_sharing_level(self):
        """Return the effective sharing level, falling back to server default."""
        if self.default_sharing_level:
            return self.default_sharing_level
        return settings.ORG_DEFAULT_SHARING_LEVEL

    def delete(self, *args, **kwargs):
        """Delete org after cleaning up members' CalDAV data.

        Must run before super().delete() because the User FK uses
        on_delete=PROTECT, which blocks deletion while members exist.
        The pre_delete signal would never fire with PROTECT, so the
        cleanup logic lives here instead.
        """
        from core.services.caldav_service import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
            cleanup_organization_caldav_data,
        )

        cleanup_organization_caldav_data(self)
        super().delete(*args, **kwargs)


class UserManager(auth_models.UserManager):
    """Custom manager for User model with additional methods."""

    def get_user_by_sub_or_email(self, sub, email):
        """Fetch existing user by sub or email."""
        try:
            return self.get(sub=sub)
        except self.model.DoesNotExist as err:
            if not email:
                return None

            if settings.OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION:
                try:
                    return self.get(email=email)
                except self.model.DoesNotExist:
                    pass
            elif (
                self.filter(email=email).exists()
                and not settings.OIDC_ALLOW_DUPLICATE_EMAILS
            ):
                raise DuplicateEmailError(
                    "We couldn't find a user with this sub but the email is already "
                    "associated with a registered user."
                ) from err
        return None


class User(AbstractBaseUser, BaseModel, auth_models.PermissionsMixin):
    """User model to work with OIDC only authentication."""

    sub_validator = validators.RegexValidator(
        regex=r"^[\w.@+-:]+\Z",
        message=(
            "Enter a valid sub. This value may contain only letters, "
            "numbers, and @/./+/-/_/: characters."
        ),
    )

    sub = models.CharField(
        "sub",
        help_text=(
            "Required. 255 characters or fewer."
            " Letters, numbers, and @/./+/-/_/: characters only."
        ),
        max_length=255,
        unique=True,
        validators=[sub_validator],
        blank=True,
        null=True,
    )

    full_name = models.CharField("full name", max_length=100, null=True, blank=True)

    email = models.EmailField(
        "identity email address", blank=True, null=True, db_index=True
    )

    # Unlike the "email" field which stores the email coming from the OIDC token, this field
    # stores the email used by staff users to login to the admin site
    admin_email = models.EmailField(
        "admin email address", unique=True, blank=True, null=True
    )

    language = models.CharField(
        max_length=10,
        choices=settings.LANGUAGES,
        default=None,
        verbose_name="language",
        help_text="The language in which the user wants to see the interface.",
        null=True,
        blank=True,
    )
    timezone = TimeZoneField(
        choices_display="WITH_GMT_OFFSET",
        use_pytz=False,
        default=settings.TIME_ZONE,
        help_text="The timezone in which the user wants to see times.",
    )
    is_device = models.BooleanField(
        "device",
        default=False,
        help_text="Whether the user is a device or a real user.",
    )
    is_staff = models.BooleanField(
        "staff status",
        default=False,
        help_text="Whether the user can log into this admin site.",
    )
    is_active = models.BooleanField(
        "active",
        default=True,
        help_text=(
            "Whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="members",
        help_text="The organization this user belongs to.",
    )

    claims = models.JSONField(
        blank=True,
        default=dict,
        help_text="Claims from the OIDC token.",
    )

    objects = UserManager()

    USERNAME_FIELD = "admin_email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "calendars_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.email or self.admin_email or str(self.id)

    def email_user(self, subject, message, from_email=None, **kwargs):
        """Email this user."""
        if not self.email:
            raise ValueError("User has no email address.")
        mail.send_mail(subject, message, from_email, [self.email], **kwargs)


def uuid_to_urlsafe(u):
    """Encode a UUID as unpadded base64url (22 chars)."""
    return base64.urlsafe_b64encode(u.bytes).rstrip(b"=").decode()


def urlsafe_to_uuid(s):
    """Decode an unpadded base64url string back to a UUID."""
    padded = s + "=" * (-len(s) % 4)
    return uuid.UUID(bytes=base64.urlsafe_b64decode(padded))


class Channel(BaseModel):
    """Integration channel for external service access to calendars.

    Follows the same pattern as the Messages Channel model. Allows external
    services (e.g. Messages) to access CalDAV on behalf of a user via a
    bearer token.

    Configuration is split between ``settings`` (public, non-sensitive) and
    ``encrypted_settings`` (sensitive data like tokens). The ``role`` for
    CalDAV access control lives in ``settings``.

    For iCal feeds, the URL contains the base64url-encoded channel ID (for
    lookup) and a base64url token (for authentication):
    ``/ical/<short_id>/<token>/<slug>.ics``.
    """

    ROLE_READER = "reader"
    ROLE_EDITOR = "editor"
    ROLE_ADMIN = "admin"
    VALID_ROLES = {ROLE_READER, ROLE_EDITOR, ROLE_ADMIN}

    name = models.CharField(
        max_length=255,
        help_text="Human-readable name for this channel.",
    )

    type = models.CharField(
        max_length=255,
        help_text="Type of channel.",
        default="caldav",
    )

    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="channels",
        help_text="User who created this channel (used for permissions and auditing).",
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="channels",
    )

    caldav_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="CalDAV path scope (e.g. /calendars/users/user@ex.com/cal/).",
    )

    is_active = models.BooleanField(default=True)

    settings = models.JSONField(
        "settings",
        default=dict,
        blank=True,
        help_text="Channel-specific configuration settings (e.g. role).",
    )

    encrypted_settings = EncryptedJSONField(
        "encrypted settings",
        default=dict,
        blank=True,
        help_text="Encrypted channel settings (e.g. token).",
    )

    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "calendars_channel"
        verbose_name = "channel"
        verbose_name_plural = "channels"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def role(self):
        """Get the role from settings, defaulting to reader."""
        return self.settings.get("role", self.ROLE_READER)

    @role.setter
    def role(self, value):
        """Set the role in settings."""
        self.settings["role"] = value

    def clean(self):
        """Validate that at least one scope is set."""
        from django.core.exceptions import ValidationError  # noqa: PLC0415, I001  # pylint: disable=C0415

        if not self.organization and not self.user and not self.caldav_path:
            raise ValidationError(
                "At least one scope must be set: organization, user, or caldav_path."
            )

    def verify_token(self, token):
        """Check that *token* matches the stored encrypted token."""
        stored = self.encrypted_settings.get("token", "")
        if not token or not stored:
            return False
        return secrets.compare_digest(token, stored)
