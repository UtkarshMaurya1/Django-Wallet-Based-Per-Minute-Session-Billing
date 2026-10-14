from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import User
from wallets.models import Wallet

from .exceptions import (
    ActiveSessionExists,
    InsufficientBalance,
    InvalidTransition,
    NotAllowed,
)
from .models import Session

Status = Session.Status
USER = Session.EndedBy.USER
PROVIDER = Session.EndedBy.PROVIDER
SYSTEM = Session.EndedBy.SYSTEM

MIN_BALANCE_MINUTES = 5


@dataclass(frozen=True)
class Transition:
    sources: frozenset
    target: str
    actors: frozenset


# The whole state machine in one place.
TRANSITIONS = {
    "assign": Transition(
        frozenset({Status.UNASSIGNED}), Status.ASSIGNED, frozenset({USER})
    ),
    "accept": Transition(
        frozenset({Status.ASSIGNED}),
        Status.ACCEPTED_BY_PROVIDER,
        frozenset({PROVIDER}),
    ),
    "start": Transition(
        frozenset({Status.ACCEPTED_BY_PROVIDER}),
        Status.IN_PROGRESS,
        frozenset({USER}),
    ),
    "end": Transition(
        frozenset({Status.IN_PROGRESS}),
        Status.COMPLETED,
        frozenset({USER, PROVIDER, SYSTEM}),
    ),
    "cancel": Transition(
        frozenset(
            {Status.UNASSIGNED, Status.ASSIGNED, Status.ACCEPTED_BY_PROVIDER}
        ),
        Status.CANCELLED,
        frozenset({USER, PROVIDER}),
    ),
}


def _actor_for(user):
    return USER if user.role == User.Role.USER else PROVIDER


def _locked(session_id):
    # Lock order across the codebase: session row first, then wallet row.
    return Session.objects.select_for_update().get(pk=session_id)


def _guard(session, action, actor, user=None):
    """Validate role, participation and current state. Returns the Transition rule."""
    rule = TRANSITIONS[action]

    if actor not in rule.actors:
        raise NotAllowed(f"A {actor} cannot perform '{action}' on a session.")
    if actor == USER and session.user_id != user.id:
        raise NotAllowed("This is not your session.")
    if actor == PROVIDER and session.provider_id != user.id:
        raise NotAllowed("You are not the provider of this session.")

    if session.status not in rule.sources:
        allowed = ", ".join(sorted(rule.sources))
        raise InvalidTransition(
            f"Cannot '{action}' a session that is '{session.status}'. "
            f"Allowed only from: {allowed}."
        )
    return rule


def _complete(session, actor, reason, now=None):
    session.status = Status.COMPLETED
    session.ended_at = now or timezone.now()
    session.ended_by = actor
    session.end_reason = reason
    session.save(update_fields=["status", "ended_at", "ended_by", "end_reason", "updated_at"])
    return session


def create_session(user):
    return Session.objects.create(user=user)


@transaction.atomic
def assign_session(session_id, user, provider_id):
    session = _locked(session_id)
    rule = _guard(session, "assign", _actor_for(user), user)

    provider = User.objects.filter(pk=provider_id, role=User.Role.PROVIDER).first()
    if provider is None:
        raise ValidationError({"provider_id": "No provider with this id."})

    session.provider = provider
    session.per_minute_cost = provider.per_minute_rate  # frozen snapshot
    session.status = rule.target
    session.save(update_fields=["provider", "per_minute_cost", "status", "updated_at"])
    return session


@transaction.atomic
def accept_session(session_id, user):
    session = _locked(session_id)
    rule = _guard(session, "accept", _actor_for(user), user)
    session.status = rule.target
    session.save(update_fields=["status", "updated_at"])
    return session


@transaction.atomic
def start_session(session_id, user, now=None):
    session = _locked(session_id)
    rule = _guard(session, "start", _actor_for(user), user)

    # Locking the wallet also serializes concurrent starts for the same user.
    wallet = Wallet.objects.select_for_update().get(user_id=session.user_id)

    required = MIN_BALANCE_MINUTES * session.per_minute_cost
    if wallet.balance < required:
        raise InsufficientBalance(
            f"Minimum balance of {required} required to start "
            f"({MIN_BALANCE_MINUTES} minutes at {session.per_minute_cost}/min); "
            f"current balance is {wallet.balance}."
        )

    if Session.objects.filter(
        user_id=session.user_id, status=Status.IN_PROGRESS
    ).exists():
        raise ActiveSessionExists("You already have a session in progress.")

    session.status = rule.target
    session.started_at = now or timezone.now()
    try:
        with transaction.atomic():  # savepoint, so an IntegrityError is recoverable
            session.save(update_fields=["status", "started_at", "updated_at"])
    except IntegrityError:
        raise ActiveSessionExists("You already have a session in progress.")
    return session


@transaction.atomic
def end_session(session_id, user, now=None):
    """
    Bill elapsed minutes before terminating a session.

    If billing detects insufficient balance, the system's
    termination reason must be preserved.
    """

    session = (
        Session.objects
        .select_for_update()
        .get(pk=session_id)
    )

    actor = _actor_for(user)

    # Reuse your existing Phase 3 state-machine validation.
    _guard(
        session,
        "end",
        actor,
        user,
    )

    # Import locally to avoid circular imports.
    from .billing import bill_session

    # Bill all elapsed whole minutes before ending.
    session = bill_session(
        session_id,
        now=now,
    )

    # Billing may already have completed the session because
    # the wallet could not cover another full minute.
    if session.status == Session.Status.COMPLETED:
        return session

    # Otherwise, complete the session normally.
    session.status = Session.Status.COMPLETED
    session.ended_at = now or timezone.now()
    session.ended_by = actor
    session.end_reason = f"Ended by {actor}"

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


@transaction.atomic
def system_end_session(session_id, reason, now=None):
    """System ends an in-progress session (e.g. 'Insufficient Balance')."""
    session = _locked(session_id)
    _guard(session, "end", SYSTEM)
    return _complete(session, SYSTEM, reason, now)


@transaction.atomic
def cancel_session(session_id, user):
    session = _locked(session_id)
    rule = _guard(session, "cancel", _actor_for(user), user)
    session.status = rule.target
    session.save(update_fields=["status", "updated_at"])
    return session