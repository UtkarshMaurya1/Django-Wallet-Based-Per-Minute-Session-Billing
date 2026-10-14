from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsUser

from . import services
from .models import Session
from .serializers import AssignSerializer, SessionSerializer


def participant_sessions(user):
    """Sessions the user takes part in, as customer or provider."""
    return Session.objects.filter(Q(user=user) | Q(provider=user))


class SessionListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsUser()]
        return super().get_permissions()

    def get(self, request):
        sessions = participant_sessions(request.user).order_by("-id")
        return Response(SessionSerializer(sessions, many=True).data)

    def post(self, request):
        session = services.create_session(request.user)
        return Response(
            SessionSerializer(session).data, status=status.HTTP_201_CREATED
        )


class SessionDetailView(APIView):
    def get(self, request, pk):
        session = get_object_or_404(participant_sessions(request.user), pk=pk)
        return Response(SessionSerializer(session).data)


class SessionActionView(APIView):
    """Base for state transitions. Non-participants get 404; the service
    enforces role and state rules (403 / 400)."""

    def perform(self, request, session):
        raise NotImplementedError

    def post(self, request, pk):
        session = get_object_or_404(participant_sessions(request.user), pk=pk)
        updated = self.perform(request, session)
        return Response(SessionSerializer(updated).data)


class AssignView(SessionActionView):
    def perform(self, request, session):
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return services.assign_session(
            session.pk, request.user, serializer.validated_data["provider_id"]
        )


class AcceptView(SessionActionView):
    def perform(self, request, session):
        return services.accept_session(session.pk, request.user)


class StartView(SessionActionView):
    def perform(self, request, session):
        return services.start_session(session.pk, request.user)


class EndView(SessionActionView):
    def perform(self, request, session):
        return services.end_session(session.pk, request.user)


class CancelView(SessionActionView):
    def perform(self, request, session):
        return services.cancel_session(session.pk, request.user)


# consultations/views.py

from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404
from django.db.models import Q

from .models import Session
from .serializers import SessionSerializer
from .billing import bill_session


class BillView(APIView):
    """
    Trigger billing for an active session.

    Only the session's user or assigned provider
    can access this endpoint.
    """

    def post(self, request, pk):

        # Restrict access to session participants.
        session = get_object_or_404(
            Session.objects.filter(
                Q(user=request.user) |
                Q(provider=request.user)
            ),
            pk=pk,
        )

        # Execute billing.
        updated_session = bill_session(
            session_id=session.pk,
        )

        return Response(
            SessionSerializer(updated_session).data
        )