from decimal import Decimal

from django.conf import settings
from django.db import models


class Session(models.Model):
    class Status(models.TextChoices):
        UNASSIGNED = "unassigned", "Unassigned"
        ASSIGNED = "assigned", "Assigned"
        ACCEPTED_BY_PROVIDER = "accepted_by_provider", "Accepted by provider"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class EndedBy(models.TextChoices):
        USER = "user", "User"
        PROVIDER = "provider", "Provider"
        SYSTEM = "system", "System"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="user_sessions"
    )
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_sessions",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=25, choices=Status.choices, default=Status.UNASSIGNED
    )

    # Snapshot of the provider's rate, taken at assignment and never changed.
    per_minute_cost = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )

    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # Billing bookkeeping (used from Phase 4).
    billed_minutes = models.PositiveIntegerField(default=0)
    total_billed = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    ended_by = models.CharField(
        max_length=10, choices=EndedBy.choices, null=True, blank=True
    )
    end_reason = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # A user can have at most one in-progress session.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="in_progress"),
                name="one_in_progress_session_per_user",
            ),
            # Anything past 'unassigned' (other than cancelled) has a provider and a cost.
            models.CheckConstraint(
                condition=(
                    models.Q(status__in=["unassigned", "cancelled"])
                    | models.Q(provider__isnull=False, per_minute_cost__isnull=False)
                ),
                name="assigned_session_has_provider_and_cost",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(per_minute_cost__isnull=True)
                    | models.Q(per_minute_cost__gt=0)
                ),
                name="session_cost_positive",
            ),
        ]

    def __str__(self):
        return f"Session {self.pk} [{self.status}]"