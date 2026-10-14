from rest_framework.permissions import BasePermission

from .models import User


class _HasRole(BasePermission):
    role = None

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == self.role)


class IsUser(_HasRole):
    role = User.Role.USER
    message = "Only users can perform this action."


class IsProvider(_HasRole):
    role = User.Role.PROVIDER
    message = "Only providers can perform this action."