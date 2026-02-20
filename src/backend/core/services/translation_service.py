"""Translation service that loads translations from the shared translations.json."""

import json
import logging
from datetime import datetime
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

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

    @classmethod
    def _load(cls):
        """Load translations from JSON file (cached at class level)."""
        if cls._translations is not None:
            return

        path = getattr(settings, "TRANSLATIONS_JSON_PATH", "")
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

        - From request: uses Django's get_language() (set by LocaleMiddleware).
        - From email: looks up User.language field.
        - Fallback: "fr".
        """
        if request is not None:
            from django.utils.translation import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
                get_language,
            )

            lang = get_language()
            if lang:
                return cls.normalize_lang(lang)

        if email:
            try:
                from core.models import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
                    User,
                )

                user = User.objects.filter(email=email).first()
                if user and user.language:
                    return cls.normalize_lang(user.language)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Failed to resolve language for email %s", email)

        return "fr"

    @staticmethod
    def normalize_lang(lang_code: str) -> str:
        """Normalize a language code to a simple 2-letter code.

        ``"fr-fr"`` -> ``"fr"``, ``"en-us"`` -> ``"en"``, ``"nl-nl"`` -> ``"nl"``.
        """
        if not lang_code:
            return "fr"
        short = lang_code.split("-")[0].lower()
        return short if short in ("en", "fr", "nl") else "fr"

    @classmethod
    def format_date(cls, dt: datetime, lang: str) -> str:
        """Format a date using translated weekday/month names.

        Returns e.g. "jeudi 23 janvier 2026" (fr)
        or "Thursday, January 23, 2026" (en).
        """
        weekday = cls.t(f"calendar.weekdaysFull.{WEEKDAY_KEYS[dt.weekday()]}", lang)
        month = cls.t(f"calendar.recurrence.months.{MONTH_KEYS[dt.month]}", lang)

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
