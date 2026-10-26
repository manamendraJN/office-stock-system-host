from django.contrib.auth import get_user_model


class EmailBackend:
    """Only supplies get_user for sessions; sign-in itself (with lockout) lives in accounts.views."""

    def authenticate(self, request, **kwargs):
        return None

    def get_user(self, user_id):
        User = get_user_model()
        try:
            user = User.objects.select_related('branch').get(pk=user_id)
        except User.DoesNotExist:
            return None
        return user if user.active else None
