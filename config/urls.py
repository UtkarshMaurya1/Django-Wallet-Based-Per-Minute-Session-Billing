from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/wallet/", include("wallets.urls")),
    path("api/sessions/", include("consultations.urls")),

]