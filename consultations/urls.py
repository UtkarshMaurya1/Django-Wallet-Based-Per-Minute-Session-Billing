from django.urls import path

from .views import (
    AcceptView,
    AssignView,
    CancelView,
    EndView,
    SessionDetailView,
    SessionListCreateView,
    StartView,
    BillView
)

urlpatterns = [
    path("", SessionListCreateView.as_view(), name="session-list"),
    path("<int:pk>/", SessionDetailView.as_view(), name="session-detail"),
    path("<int:pk>/assign/", AssignView.as_view(), name="session-assign"),
    path("<int:pk>/accept/", AcceptView.as_view(), name="session-accept"),
    path("<int:pk>/start/", StartView.as_view(), name="session-start"),
    path("<int:pk>/end/", EndView.as_view(), name="session-end"),
    path("<int:pk>/cancel/", CancelView.as_view(), name="session-cancel"),
    path("<int:pk>/bill/", BillView.as_view(), name="session-bill"),
]