from decimal import Decimal

from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import User

from .models import RechargeTransaction, Wallet


def make_user(username="alice"):
    return User.objects.create_user(username, password="pass12345", role="USER")


def make_provider(username="doc"):
    return User.objects.create_user(
        username,
        password="pass12345",
        role="PROVIDER",
        per_minute_rate=Decimal("50.00"),
    )


def balance_of(user):
    return Wallet.objects.get(user=user).balance


class WalletTests(APITestCase):
    def test_wallet_created_with_zero_balance(self):
        user = make_user()
        self.assertEqual(balance_of(user), Decimal("0.00"))

    def test_view_balance(self):
        user = make_user()
        Wallet.objects.filter(user=user).update(balance=Decimal("120.50"))
        self.client.force_authenticate(user)
        res = self.client.get(reverse("wallet"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(res.data["balance"]), Decimal("120.50"))

    def test_wallet_requires_auth(self):
        res = self.client.get(reverse("wallet"))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_db_rejects_negative_balance(self):
        user = make_user()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(user=user).update(balance=Decimal("-1.00"))


class RechargeTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)

    def initiate(self, amount="500.00"):
        return self.client.post(
            reverse("recharge-initiate"), {"amount": amount}, format="json"
        )

    def callback(self, reference, new_status):
        # Fresh, unauthenticated client: the gateway is not a logged-in user.
        return APIClient().post(
            reverse("recharge-callback"),
            {"reference": reference, "status": new_status},
            format="json",
        )

    def test_initiate_creates_pending_without_crediting(self):
        res = self.initiate()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "pending")
        self.assertEqual(balance_of(self.user), Decimal("0.00"))

    def test_initiate_rejects_non_positive_amount(self):
        for bad in ["0", "-10", "abc"]:
            self.assertEqual(
                self.initiate(bad).status_code, status.HTTP_400_BAD_REQUEST
            )

    def test_provider_cannot_recharge(self):
        self.client.force_authenticate(make_provider())
        self.assertEqual(self.initiate().status_code, status.HTTP_403_FORBIDDEN)

    def test_initiate_requires_auth(self):
        res = APIClient().post(
            reverse("recharge-initiate"), {"amount": "10"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_success_callback_credits_wallet(self):
        ref = self.initiate("500.00").data["reference"]
        res = self.callback(ref, "success")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["credited"])
        self.assertEqual(balance_of(self.user), Decimal("500.00"))

    def test_duplicate_success_callback_credits_once(self):
        ref = self.initiate("500.00").data["reference"]
        first = self.callback(ref, "success")
        second = self.callback(ref, "success")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(first.data["credited"])
        self.assertFalse(second.data["credited"])
        self.assertEqual(balance_of(self.user), Decimal("500.00"))

    def test_failed_callback_does_not_credit(self):
        ref = self.initiate().data["reference"]
        res = self.callback(ref, "failed")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data["credited"])
        self.assertEqual(balance_of(self.user), Decimal("0.00"))

    def test_success_after_failed_is_conflict(self):
        ref = self.initiate().data["reference"]
        self.callback(ref, "failed")
        res = self.callback(ref, "success")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(balance_of(self.user), Decimal("0.00"))

    def test_failed_after_success_is_conflict_and_keeps_credit(self):
        ref = self.initiate("500.00").data["reference"]
        self.callback(ref, "success")
        res = self.callback(ref, "failed")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(balance_of(self.user), Decimal("500.00"))
        self.assertEqual(
            RechargeTransaction.objects.get(reference=ref).status, "success"
        )

    def test_unknown_reference_is_404(self):
        res = self.callback("RCH-DOESNOTEXIST", "success")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_callback_status_is_400(self):
        ref = self.initiate().data["reference"]
        res = self.callback(ref, "pending")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)