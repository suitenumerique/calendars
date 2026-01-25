"""
Core application factories
"""

from django.conf import settings
from django.contrib.auth.hashers import make_password

import factory.fuzzy
from faker import Faker

from core import models

fake = Faker()


class UserFactory(factory.django.DjangoModelFactory):
    """A factory to random users for testing purposes."""

    class Meta:
        model = models.User
        skip_postgeneration_save = True

    sub = factory.Sequence(lambda n: f"user{n!s}")
    email = factory.Faker("email")
    full_name = factory.Faker("name")
    short_name = factory.Faker("first_name")
    language = factory.fuzzy.FuzzyChoice([lang[0] for lang in settings.LANGUAGES])
    password = make_password("password")


class CalendarFactory(factory.django.DjangoModelFactory):
    """A factory to create calendars for testing purposes."""

    class Meta:
        model = models.Calendar

    owner = factory.SubFactory(UserFactory)
    name = factory.Faker("sentence", nb_words=3)
    color = factory.Faker("hex_color")
    description = factory.Faker("paragraph")
    is_default = False
    is_visible = True
    caldav_path = factory.LazyAttribute(
        lambda obj: f"/calendars/{obj.owner.email}/{fake.uuid4()}"
    )


class CalendarSubscriptionTokenFactory(factory.django.DjangoModelFactory):
    """A factory to create calendar subscription tokens for testing purposes."""

    class Meta:
        model = models.CalendarSubscriptionToken

    owner = factory.SubFactory(UserFactory)
    caldav_path = factory.LazyAttribute(
        lambda obj: f"/calendars/{obj.owner.email}/{fake.uuid4()}/"
    )
    calendar_name = factory.Faker("sentence", nb_words=3)
    is_active = True
