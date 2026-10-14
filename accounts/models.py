from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        USER = "USER", "User"
        PROVIDER = "PROVIDER", "Provider"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
    # Providers only: price per minute of a session. Copied onto a Session at creation.
    per_minute_rate = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )

    class Meta:
        constraints = [
            # isnull=False is explicit because NULL > 0 is "unknown", which a
            # CHECK constraint would let through.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        role="PROVIDER",
                        per_minute_rate__isnull=False,
                        per_minute_rate__gt=0,
                    )
                    | models.Q(role="USER", per_minute_rate__isnull=True)
                ),
                name="provider_has_rate_user_does_not",
            )
        ]

    def __str__(self):
        return f"{self.username} ({self.role})"