from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from wallets.models import Wallet

from .models import Session


def _end_for_insufficient_balance(session, now):
    """Complete an active session if its wallet cannot cover another minute."""
    session.status = Session.Status.COMPLETED
    session.ended_at = now
    session.ended_by = Session.EndedBy.SYSTEM
    session.end_reason = "Insufficient Balance"


@transaction.atomic
def bill_session(session_id, now=None):
    """
    Bill newly elapsed whole minutes for a session.

    Each minute is charged at most once. If the remaining wallet balance
    cannot cover another minute, the active session is completed immediately.
    `now` can be supplied to make billing deterministic in tests.
    """
    now = now or timezone.now()

    # Lock the session to prevent concurrent billing.
    session = (
        Session.objects
        .select_for_update()
        .get(pk=session_id)
    )

    # A session that never started cannot be billed.
    if session.started_at is None:
        return session

    # Only active or completed sessions can be billed.
    if session.status not in (
        Session.Status.IN_PROGRESS,
        Session.Status.COMPLETED,
    ):
        return session

    # Completed sessions must never be billed beyond their end time.
    end_time = (
        session.ended_at
        if session.status == Session.Status.COMPLETED
        else now
    )

    if end_time is None:
        return session

    # Calculate fully elapsed minutes.
    elapsed_seconds = max(
        0,
        (end_time - session.started_at).total_seconds(),
    )
    billable_minutes = int(elapsed_seconds // 60)

    # Only charge minutes that have not already been billed.
    minutes_due = max(
        0,
        billable_minutes - session.billed_minutes,
    )

    # Lock the wallet after locking the session.
    wallet = (
        Wallet.objects
        .select_for_update()
        .get(user_id=session.user_id)
    )

    rate = session.per_minute_cost

    if rate is None or rate <= Decimal("0.00"):
        raise ValueError(
            "A started session must have a positive per-minute cost."
        )

    # Even when no new minute is due, check whether an active session
    # can afford its next minute.
    if minutes_due == 0:
        if (
            session.status == Session.Status.IN_PROGRESS
            and wallet.balance < rate
        ):
            _end_for_insufficient_balance(session, now)
            session.save(
                update_fields=[
                    "status",
                    "ended_at",
                    "ended_by",
                    "end_reason",
                    "updated_at",
                ]
            )
        return session

    minutes_charged = 0

    # Charge each newly elapsed minute separately.
    for _ in range(minutes_due):
        # The next complete minute cannot be paid for.
        if wallet.balance < rate:
            if session.status == Session.Status.IN_PROGRESS:
                _end_for_insufficient_balance(session, now)
            break

        wallet.balance -= rate
        session.total_billed += rate
        session.billed_minutes += 1
        minutes_charged += 1

    if (
        session.status == Session.Status.IN_PROGRESS
        and wallet.balance < rate
    ):
        _end_for_insufficient_balance(session, now)

    # Save the wallet only if money was deducted.
    if minutes_charged:
        wallet.save(
            update_fields=[
                "balance",
                "updated_at",
            ]
        )

    # Persist billing progress and any automatic termination.
    session.save(
        update_fields=[
            "billed_minutes",
            "total_billed",
            "status",
            "ended_at",
            "ended_by",
            "end_reason",
            "updated_at",
        ]
    )

    return session
