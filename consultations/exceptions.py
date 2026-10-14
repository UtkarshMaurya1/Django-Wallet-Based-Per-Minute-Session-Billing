from rest_framework import status
from rest_framework.exceptions import APIException


class InvalidTransition(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid state transition."
    default_code = "invalid_transition"


class InsufficientBalance(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Insufficient wallet balance."
    default_code = "insufficient_balance"


class ActiveSessionExists(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "User already has an in-progress session."
    default_code = "active_session_exists"


class NotAllowed(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "You are not allowed to perform this action."
    default_code = "not_allowed"