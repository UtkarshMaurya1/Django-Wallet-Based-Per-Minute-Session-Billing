from decimal import Decimal

from rest_framework import serializers

from .models import RechargeTransaction, Wallet


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ["balance", "updated_at"]
        read_only_fields = fields


class RechargeInitiateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )


class RechargeTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RechargeTransaction
        fields = ["id", "reference", "amount", "status", "created_at"]
        read_only_fields = fields


class RechargeCallbackSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=40)
    status = serializers.ChoiceField(
        choices=[
            RechargeTransaction.Status.SUCCESS,
            RechargeTransaction.Status.FAILED,
        ]
    )