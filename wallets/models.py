import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


def generate_reference():
    return f"RCH-{uuid.uuid4().hex[:20].upper()}"


class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet"
    )
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(balance__gte=0),
                name="wallet_balance_non_negative",
            )
        ]

    def __str__(self):
        return f"Wallet({self.user_id}, {self.balance})"


class RechargeTransaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recharges"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(
        max_length=40, unique=True, default=generate_reference, editable=False
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="recharge_amount_positive",
            )
        ]

    def __str__(self):
        return f"{self.reference} {self.amount} [{self.status}]"