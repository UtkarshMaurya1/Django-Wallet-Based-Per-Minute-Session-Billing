from django.urls import path

from .views import RechargeCallbackView, RechargeInitiateView, WalletView

urlpatterns = [
    path("", WalletView.as_view(), name="wallet"),
    path("recharge/", RechargeInitiateView.as_view(), name="recharge-initiate"),
    path(
        "recharge/callback/", RechargeCallbackView.as_view(), name="recharge-callback"
    ),
]