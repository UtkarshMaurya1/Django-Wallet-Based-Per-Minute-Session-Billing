from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsUser

from . import services
from .exceptions import RechargeConflict
from .models import RechargeTransaction, Wallet
from .serializers import (
    RechargeCallbackSerializer,
    RechargeInitiateSerializer,
    RechargeTransactionSerializer,
    WalletSerializer,
)


class WalletView(APIView):
    def get(self, request):
        wallet = Wallet.objects.get(user=request.user)
        return Response(WalletSerializer(wallet).data)

class RechargeInitiateView(APIView):
    permission_classes = [IsUser]

    def post(self, request):
        serializer = RechargeInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        txn = services.initiate_recharge(
            request.user, serializer.validated_data["amount"]
        )
        return Response(
            RechargeTransactionSerializer(txn).data, status=status.HTTP_201_CREATED
        )


class RechargeCallbackView(APIView):
    """Mock payment-gateway webhook. Unauthenticated by design (see decisions note)."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RechargeCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            txn, credited = services.process_recharge_callback(
                reference=serializer.validated_data["reference"],
                new_status=serializer.validated_data["status"],
            )
        except RechargeTransaction.DoesNotExist:
            return Response(
                {"detail": "Unknown reference."}, status=status.HTTP_404_NOT_FOUND
            )
        except RechargeConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response(
            {"reference": txn.reference, "status": txn.status, "credited": credited}
        )