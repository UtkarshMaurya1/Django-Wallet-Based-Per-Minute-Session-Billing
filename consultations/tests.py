from decimal import Decimal

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from wallets.models import Wallet

from . import services
from .exceptions import InvalidTransition
from .models import Session
from datetime import timedelta

from .billing import bill_session


def make_user(username="alice"):
    return User.objects.create_user(username, password="pass12345", role="USER")


def make_provider(username="doc", rate="50.00"):
    return User.objects.create_user(
        username,
        password="pass12345",
        role="PROVIDER",
        per_minute_rate=Decimal(rate),
    )


def fund(user, amount):
    Wallet.objects.filter(user=user).update(balance=Decimal(amount))


def api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class SessionTestBase(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.provider = make_provider()

    # --- helpers -------------------------------------------------------
    def new_session(self, user=None):
        return api(user or self.user).post(reverse("session-list")).data["id"]

    def act(self, user, name, session_id, data=None):
        return api(user).post(
            reverse(f"session-{name}", args=[session_id]), data or {}, format="json"
        )

    def assigned_session(self, user=None, provider=None):
        user, provider = user or self.user, provider or self.provider
        sid = self.new_session(user)
        self.act(user, "assign", sid, {"provider_id": provider.id})
        return sid

    def accepted_session(self, user=None, provider=None):
        user, provider = user or self.user, provider or self.provider
        sid = self.assigned_session(user, provider)
        self.act(provider, "accept", sid)
        return sid

    def in_progress_session(self, user=None, provider=None):
        user, provider = user or self.user, provider or self.provider
        sid = self.accepted_session(user, provider)
        self.act(user, "start", sid)
        return sid

    def status_of(self, sid):
        return Session.objects.get(pk=sid).status


class CreateAndAssignTests(SessionTestBase):
    def test_create_session_is_unassigned(self):
        res = api(self.user).post(reverse("session-list"))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "unassigned")
        self.assertIsNone(res.data["provider"])
        self.assertIsNone(res.data["per_minute_cost"])

    def test_provider_cannot_create_session(self):
        res = api(self.provider).post(reverse("session-list"))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_requires_auth(self):
        res = APIClient().post(reverse("session-list"))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_assign_sets_provider_and_cost(self):
        sid = self.new_session()
        res = self.act(self.user, "assign", sid, {"provider_id": self.provider.id})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "assigned")
        self.assertEqual(res.data["provider"], self.provider.id)
        self.assertEqual(Decimal(res.data["per_minute_cost"]), Decimal("50.00"))

    def test_assign_to_non_provider_is_400(self):
        sid = self.new_session()
        other_user = make_user("bob")
        for bad_id in [other_user.id, 99999]:
            res = self.act(self.user, "assign", sid, {"provider_id": bad_id})
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.status_of(sid), "unassigned")

    def test_assign_twice_is_400(self):
        sid = self.assigned_session()
        res = self.act(self.user, "assign", sid, {"provider_id": self.provider.id})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class AcceptTests(SessionTestBase):
    def test_accept_permissions_and_success(self):
        sid = self.assigned_session()

        # A different provider is not a participant -> 404.
        other = make_provider("doc2")
        self.assertEqual(
            self.act(other, "accept", sid).status_code, status.HTTP_404_NOT_FOUND
        )
        # The customer cannot accept -> 403.
        self.assertEqual(
            self.act(self.user, "accept", sid).status_code, status.HTTP_403_FORBIDDEN
        )
        # The assigned provider can.
        res = self.act(self.provider, "accept", sid)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "accepted_by_provider")


class StartTests(SessionTestBase):
    def test_start_requires_acceptance(self):
        fund(self.user, "1000")
        sid = self.assigned_session()
        res = self.act(self.user, "start", sid)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.status_of(sid), "assigned")

    def test_start_with_exact_minimum_balance_succeeds(self):
        fund(self.user, "250.00")  # 5 x 50
        sid = self.accepted_session()
        res = self.act(self.user, "start", sid)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "in_progress")
        self.assertIsNotNone(res.data["started_at"])

    def test_start_below_minimum_balance_is_400(self):
        sid = self.accepted_session()
        for amount in ["0.00", "200.00", "249.99"]:
            with self.subTest(balance=amount):
                fund(self.user, amount)
                res = self.act(self.user, "start", sid)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(self.status_of(sid), "accepted_by_provider")

    def test_provider_cannot_start(self):
        fund(self.user, "1000")
        sid = self.accepted_session()
        res = self.act(self.provider, "start", sid)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cost_is_frozen_after_rate_change(self):
        fund(self.user, "1000")
        sid = self.accepted_session()
        User.objects.filter(pk=self.provider.pk).update(per_minute_rate=Decimal("999"))
        self.act(self.user, "start", sid)
        self.assertEqual(
            Session.objects.get(pk=sid).per_minute_cost, Decimal("50.00")
        )


class ActiveSessionTests(SessionTestBase):
    def test_second_active_session_rejected(self):
        fund(self.user, "1000")
        first = self.in_progress_session()
        second = self.accepted_session()

        res = self.act(self.user, "start", second)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.status_of(second), "accepted_by_provider")

        # Once the first one ends, the second can start.
        self.act(self.user, "end", first)
        res = self.act(self.user, "start", second)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_db_constraint_blocks_two_in_progress(self):
        fields = dict(
            user=self.user,
            provider=self.provider,
            per_minute_cost=Decimal("50"),
            status="in_progress",
            started_at=timezone.now(),
        )
        Session.objects.create(**fields)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Session.objects.create(**fields)


class EndTests(SessionTestBase):
    def test_end_before_start_is_400(self):
        for make in (self.assigned_session, self.accepted_session):
            with self.subTest(state=make.__name__):
                sid = make()
                res = self.act(self.user, "end", sid)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("Cannot 'end'", res.data["detail"])

    def test_user_can_end(self):
        fund(self.user, "1000")
        sid = self.in_progress_session()
        res = self.act(self.user, "end", sid)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "completed")
        self.assertEqual(res.data["ended_by"], "user")
        self.assertIsNotNone(res.data["ended_at"])

    def test_provider_can_end(self):
        fund(self.user, "1000")
        sid = self.in_progress_session()
        res = self.act(self.provider, "end", sid)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["ended_by"], "provider")

    def test_end_twice_is_400(self):
        fund(self.user, "1000")
        sid = self.in_progress_session()
        self.act(self.user, "end", sid)
        res = self.act(self.user, "end", sid)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_system_end_records_reason(self):
        fund(self.user, "1000")
        sid = self.in_progress_session()
        session = services.system_end_session(sid, "Insufficient Balance")
        self.assertEqual(session.status, "completed")
        self.assertEqual(session.ended_by, "system")
        self.assertEqual(session.end_reason, "Insufficient Balance")
        self.assertIsNotNone(session.ended_at)

    def test_system_end_requires_in_progress(self):
        sid = self.accepted_session()
        with self.assertRaises(InvalidTransition):
            services.system_end_session(sid, "Insufficient Balance")


class CancelTests(SessionTestBase):
    def test_user_can_cancel_unassigned(self):
        sid = self.new_session()
        res = self.act(self.user, "cancel", sid)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "cancelled")

    def test_provider_can_cancel_accepted(self):
        sid = self.accepted_session()
        res = self.act(self.provider, "cancel", sid)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "cancelled")

    def test_cannot_cancel_in_progress(self):
        fund(self.user, "1000")
        sid = self.in_progress_session()
        res = self.act(self.user, "cancel", sid)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.status_of(sid), "in_progress")


class VisibilityTests(SessionTestBase):
    def test_non_participant_gets_404(self):
        sid = self.accepted_session()
        stranger = make_user("mallory")
        self.assertEqual(
            api(stranger).get(reverse("session-detail", args=[sid])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.act(stranger, "cancel", sid).status_code, status.HTTP_404_NOT_FOUND
        )

    def test_list_only_shows_own_sessions(self):
        mine = self.new_session()
        other_user = make_user("bob")
        self.new_session(other_user)

        res = api(self.user).get(reverse("session-list"))
        self.assertEqual([s["id"] for s in res.data], [mine])

    def test_provider_sees_assigned_sessions(self):
        sid = self.assigned_session()
        self.new_session()  # unassigned: provider must not see it
        res = api(self.provider).get(reverse("session-list"))
        self.assertEqual([s["id"] for s in res.data], [sid])


class BillingTests(SessionTestBase):
    def _set_started_at(self, session_id, started_at):
        Session.objects.filter(pk=session_id).update(
            started_at=started_at
        )

    def test_billing_ends_session_when_balance_reaches_zero(self):
        fund(self.user, "250.00")  # 5 minutes × ₹50
        sid = self.in_progress_session()

        now = timezone.now()
        self._set_started_at(
            sid,
            now - timedelta(minutes=5),
        )

        session = bill_session(sid, now=now)

        self.assertEqual(
            session.status,
            Session.Status.COMPLETED,
        )
        self.assertEqual(
            session.ended_by,
            Session.EndedBy.SYSTEM,
        )
        self.assertEqual(
            session.end_reason,
            "Insufficient Balance",
        )
        self.assertEqual(session.billed_minutes, 5)
        self.assertEqual(
            session.total_billed,
            Decimal("250.00"),
        )
        self.assertEqual(
            Wallet.objects.get(user=self.user).balance,
            Decimal("0.00"),
        )
        self.assertEqual(session.ended_at, now)

    def test_billing_ends_session_with_insufficient_remainder(self):
        fund(self.user, "275.00")
        sid = self.in_progress_session()

        now = timezone.now()
        self._set_started_at(
            sid,
            now - timedelta(minutes=5),
        )

        session = bill_session(sid, now=now)

        self.assertEqual(
            session.status,
            Session.Status.COMPLETED,
        )
        self.assertEqual(
            session.ended_by,
            Session.EndedBy.SYSTEM,
        )
        self.assertEqual(
            session.end_reason,
            "Insufficient Balance",
        )
        self.assertEqual(session.billed_minutes, 5)
        self.assertEqual(
            session.total_billed,
            Decimal("250.00"),
        )
        self.assertEqual(
            Wallet.objects.get(user=self.user).balance,
            Decimal("25.00"),
        )

    def test_duplicate_billing_does_not_charge_twice(self):
        fund(self.user, "500.00")
        sid = self.in_progress_session()

        now = timezone.now()
        self._set_started_at(
            sid,
            now - timedelta(minutes=2),
        )

        first = bill_session(sid, now=now)
        second = bill_session(sid, now=now)

        self.assertEqual(first.billed_minutes, 2)
        self.assertEqual(second.billed_minutes, 2)
        self.assertEqual(
            second.total_billed,
            Decimal("100.00"),
        )
        self.assertEqual(
            Wallet.objects.get(user=self.user).balance,
            Decimal("400.00"),
        )
        self.assertEqual(
            second.status,
            Session.Status.IN_PROGRESS,
        )



def test_happy_path_recharge_bill_two_minutes_and_end(self):
    # 1. Recharge the wallet through the mock recharge flow.
    client = api(self.user)

    recharge_response = client.post(
        reverse("recharge-initiate"),
        {"amount": "500.00"},
        format="json",
    )
    self.assertEqual(recharge_response.status_code, 201)

    reference = recharge_response.data["reference"]

    callback_response = APIClient().post(
        reverse("recharge-callback"),
        {"reference": reference, "status": "success"},
        format="json",
    )
    self.assertEqual(callback_response.status_code, 200)
    self.assertTrue(callback_response.data["credited"])

    self.assertEqual(
        Wallet.objects.get(user=self.user).balance,
        Decimal("500.00"),
    )

    # 2. Create, assign, accept, and start the session.
    sid = self.new_session()
    self.assertEqual(
        self.act(
            self.user,
            "assign",
            sid,
            {"provider_id": self.provider.id},
        ).status_code,
        200,
    )
    self.assertEqual(
        self.act(self.provider, "accept", sid).status_code,
        200,
    )
    self.assertEqual(
        self.act(self.user, "start", sid).status_code,
        200,
    )

    # 3. Simulate exactly two elapsed minutes.
    now = timezone.now()
    Session.objects.filter(pk=sid).update(
        started_at=now - timedelta(minutes=2)
    )

    # 4. Bill two minutes, then end the session.
    billed_session = bill_session(sid, now=now)

    self.assertEqual(billed_session.billed_minutes, 2)
    self.assertEqual(
        billed_session.total_billed,
        Decimal("100.00"),
    )

    ended_session = services.end_session(
        sid,
        self.user,
        now=now,
    )

    # 5. Verify the final state and wallet balance.
    self.assertEqual(
        ended_session.status,
        Session.Status.COMPLETED,
    )
    self.assertEqual(ended_session.ended_by, "user")
    self.assertEqual(ended_session.billed_minutes, 2)
    self.assertEqual(
        Wallet.objects.get(user=self.user).balance,
        Decimal("400.00"),
    )
