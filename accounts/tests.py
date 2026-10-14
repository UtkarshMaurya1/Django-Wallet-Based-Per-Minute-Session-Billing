from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from .models import User
from .permissions import IsProvider, IsUser


class RegisterAndLoginTests(APITestCase):
    def register(self, **overrides):
        payload = {"username": "alice", "password": "pass12345", "role": "USER"}
        payload.update(overrides)
        return self.client.post(reverse("register"), payload, format="json")

    def test_register_user_returns_token(self):
        res = self.register()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("token", res.data)
        self.assertNotIn("password", res.data["user"])

    def test_register_provider_with_rate(self):
        res = self.register(username="doc", role="PROVIDER", per_minute_rate="50.00")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            User.objects.get(username="doc").per_minute_rate, Decimal("50.00")
        )

    def test_provider_requires_positive_rate(self):
        res = self.register(username="doc", role="PROVIDER")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.register(username="doc", role="PROVIDER", per_minute_rate="0")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_cannot_have_rate(self):
        res = self.register(per_minute_rate="10.00")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_returns_token(self):
        self.register()
        res = self.client.post(
            reverse("login"),
            {"username": "alice", "password": "pass12345"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("token", res.data)

    def test_me_requires_auth_and_returns_role(self):
        self.assertEqual(
            self.client.get(reverse("me")).status_code, status.HTTP_401_UNAUTHORIZED
        )
        token = self.register().data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        res = self.client.get(reverse("me"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["role"], "USER")


class PermissionTests(APITestCase):
    def _request_as(self, user):
        request = APIRequestFactory().get("/")
        request.user = user
        return request

    def test_role_permissions(self):
        user = User.objects.create_user("u", password="x", role="USER")
        provider = User.objects.create_user(
            "p", password="x", role="PROVIDER", per_minute_rate=Decimal("50")
        )
        self.assertTrue(IsUser().has_permission(self._request_as(user), None))
        self.assertFalse(IsUser().has_permission(self._request_as(provider), None))
        self.assertTrue(IsProvider().has_permission(self._request_as(provider), None))
        self.assertFalse(IsProvider().has_permission(self._request_as(user), None))