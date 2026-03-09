"""
Core application factories
"""

import secrets

from django.conf import settings
from django.contrib.auth.hashers import make_password

import factory.fuzzy
from faker import Faker

from core import models

fake = Faker()


class OrganizationFactory(factory.django.DjangoModelFactory):
    """A factory to create organizations for testing purposes."""

    class Meta:
        model = models.Organization

    name = factory.Faker("company")
    external_id = factory.Sequence(lambda n: f"org-{n}")


class UserFactory(factory.django.DjangoModelFactory):
    """A factory to random users for testing purposes."""

    class Meta:
        model = models.User
        skip_postgeneration_save = True

    sub = factory.Sequence(lambda n: f"user{n!s}")
    email = factory.Faker("email")
    full_name = factory.Faker("name")
    language = factory.fuzzy.FuzzyChoice([lang[0] for lang in settings.LANGUAGES])
    password = make_password("password")
    organization = factory.SubFactory(OrganizationFactory)


class ChannelFactory(factory.django.DjangoModelFactory):
    """A factory to create channels for testing purposes."""

    class Meta:
        model = models.Channel

    name = factory.Faker("sentence", nb_words=3)
    user = factory.SubFactory(UserFactory)
    settings = factory.LazyFunction(lambda: {"role": "reader"})
    encrypted_settings = factory.LazyFunction(
        lambda: {"token": secrets.token_urlsafe(16)}
    )


class ICalFeedChannelFactory(ChannelFactory):
    """A factory to create ical-feed channels."""

    type = "ical-feed"
    caldav_path = factory.LazyAttribute(
        lambda obj: f"/calendars/users/{obj.user.email}/{fake.uuid4()}/"
    )
    settings = factory.LazyAttribute(
        lambda obj: {"role": "reader", "calendar_name": fake.sentence(nb_words=3)}
    )
