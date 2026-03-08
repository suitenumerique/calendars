"""Viewsets for the e2e app."""

from django.contrib.auth import login

import rest_framework as drf
from rest_framework import response as drf_response
from rest_framework import status
from rest_framework.permissions import AllowAny

from core import models

from e2e.serializers import E2EAuthSerializer


class UserAuthViewSet(drf.viewsets.ViewSet):
    """Viewset to handle user authentication"""

    permission_classes = [AllowAny]
    authentication_classes = []

    def create(self, request):
        """
        POST /api/v1.0/e2e/user-auth/
        Create a user with the given email if it doesn't exist and log them in
        """
        serializer = E2EAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create user if doesn't exist
        email = serializer.validated_data["email"]
        user = models.User.objects.filter(email=email).first()
        if not user:
            domain = email.split("@")[-1] if "@" in email else "e2e"
            org, _ = models.Organization.objects.get_or_create(
                external_id=domain,
                defaults={"name": domain},
            )
            user = models.User(email=email, organization=org)
            user.set_unusable_password()
            user.save()

        login(request, user, "django.contrib.auth.backends.ModelBackend")

        return drf_response.Response({"email": user.email}, status=status.HTTP_200_OK)
