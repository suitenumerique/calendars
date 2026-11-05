"""Translation service that loads translations from the shared translations.json."""

import json
import logging
import threading
from datetime import datetime
from typing import Optional

from django.conf import settings
from django.utils.translation.trans_real import parse_accept_lang_header

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = ("en", "fr", "nl")


def _supported_language(code: str) -> Optional[str]:
    """Return the primary subtag of a BCP 47 tag ("nl-BE" gives "nl"), if supported."""
    short = code.split("-")[0].lower()
    return short if short in SUPPORTED_LANGUAGES else None


WEEKDAY_KEYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

MONTH_KEYS = [
    "",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


class TranslationService:
    """Lightweight translation service backed by translations.json."""

    _translations = None
    _load_lock = threading.Lock()

    @classmethod
    def _load(cls):
        """Load translations from JSON file (cached at class level)."""
        if cls._translations is not None:
            return

        with cls._load_lock:
            # Double-check after acquiring lock
            if cls._translations is not None:
                return

            path = settings.TRANSLATIONS_JSON_PATH
            if not path:
                raise RuntimeError("TRANSLATIONS_JSON_PATH setting is not configured")

            with open(path, encoding="utf-8") as f:
                cls._translations = json.load(f)

    @classmethod
    def _get_nested(cls, data: dict, dotted_key: str):
        """Traverse a nested dict using dot-separated key."""
        parts = dotted_key.split(".")
        current = data
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current if isinstance(current, str) else None

    @classmethod
    def t(cls, key: str, lang: str = "en", **kwargs) -> str:  # pylint: disable=invalid-name
        """Look up a translation key with interpolation.

        Fallback chain: lang -> "en" -> key itself.
        Interpolation: ``{{var}}`` patterns are replaced from kwargs.
        """
        cls._load()

        for try_lang in (lang, "en"):
            lang_data = cls._translations.get(try_lang, {})
            translation_data = lang_data.get("translation", lang_data)
            value = cls._get_nested(translation_data, key)
            if value is not None:
                for k, v in kwargs.items():
                    value = value.replace("{{" + k + "}}", str(v))
                return value

        return key

    @classmethod
    def resolve_language(cls, request=None, email: Optional[str] = None) -> str:
        """Determine the best language for a request or email recipient.

        - From email: the saved language of the user with this email, if it
          is supported.
        - From request: the Accept-Language header of the browser.
        - Fallback: "fr".

        We do not use the Django functions. get_language() gives the active
        Django language, or LANGUAGE_CODE. It does not read the request.
        get_language_from_request() reads the request, but it selects from
        the LANGUAGES setting, which has German, and falls back to English.
        This service supports en, fr and nl, and falls back to French.
        """
        if email:
            try:
                from django.contrib.auth import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
                    get_user_model,
                )

                user = get_user_model().objects.filter(email__iexact=email).first()
                lang = (
                    _supported_language(user.language)
                    if user and user.language
                    else None
                )
                if lang:
                    return lang
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Failed to resolve language for recipient")

        if request is not None:
            lang = cls._language_from_header(
                request.META.get("HTTP_ACCEPT_LANGUAGE", "")
            )
            if lang:
                return lang

        return "fr"

    @staticmethod
    def _language_from_header(header: str) -> Optional[str]:
        """Return the first supported language of an Accept-Language header."""
        for code, quality in parse_accept_lang_header(header):
            # A quality of 0 means that the browser does not accept the language.
            lang = _supported_language(code) if quality > 0 else None
            if lang:
                return lang
        return None

    @staticmethod
    def normalize_lang(lang_code: str) -> str:
        """Normalize a language code to a simple 2-letter code.

        ``"fr-fr"`` -> ``"fr"``, ``"en-us"`` -> ``"en"``, ``"nl-nl"`` -> ``"nl"``.
        """
        if not lang_code:
            return "fr"
        return _supported_language(lang_code) or "fr"

    @classmethod
    def format_date(cls, dt: datetime, lang: str) -> str:
        """Format a date using translated weekday/month names.

        Returns e.g. "jeudi 23 janvier 2026" (fr)
        or "Thursday, January 23, 2026" (en).
        """
        weekday = cls.t(f"calendar.weekdaysFull.{WEEKDAY_KEYS[dt.weekday()]}", lang)
        month = cls.t(f"calendar.recurrence.monthNames.{MONTH_KEYS[dt.month]}", lang)

        if lang == "fr":
            month = month.lower()
            return f"{weekday} {dt.day} {month} {dt.year}"
        if lang == "nl":
            month = month.lower()
            return f"{weekday} {dt.day} {month} {dt.year}"

        # English format
        return f"{weekday}, {month} {dt.day}, {dt.year}"

    @classmethod
    def reset(cls):
        """Reset cached translations (useful for tests)."""
        cls._translations = None
