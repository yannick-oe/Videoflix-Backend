"""Token generators of the authentication app."""

from django.contrib.auth.tokens import PasswordResetTokenGenerator


class ActivationTokenGenerator(PasswordResetTokenGenerator):
    """Token generator for single-use account activation links."""

    def _make_hash_value(self, user, timestamp):
        """Return the hash payload extended by the activation state."""
        base = super()._make_hash_value(user, timestamp)
        return f"{base}{user.is_active}"


activation_token_generator = ActivationTokenGenerator()
