"""Serializers of the authentication API."""

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from auth_app.tokens import activation_token_generator

EMAIL_TAKEN_MESSAGE = "This email address is already registered."
PASSWORD_MISMATCH_MESSAGE = "The passwords do not match."


class NormalizedEmailField(serializers.EmailField):
    """Email field that lowercases the domain of the address."""

    def to_internal_value(self, data):
        """Return the normalized address."""
        address = super().to_internal_value(data)
        return User.objects.normalize_email(address)


class RegistrationSerializer(serializers.ModelSerializer):
    """Serializer that creates an inactive account from an email."""

    email = NormalizedEmailField(
        validators=[
            UniqueValidator(
                queryset=User.objects.all(), message=EMAIL_TAKEN_MESSAGE
            )
        ]
    )
    password = serializers.CharField(write_only=True)
    confirmed_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["email", "password", "confirmed_password"]

    def validate(self, attrs):
        """Reject a wrong confirmation or a password Django rejects."""
        if attrs["password"] != attrs["confirmed_password"]:
            raise serializers.ValidationError(
                {"confirmed_password": PASSWORD_MISMATCH_MESSAGE}
            )
        self._validate_password_strength(attrs)
        return attrs

    def _validate_password_strength(self, attrs):
        """Run Django's password validators against the new account."""
        candidate = User(username=attrs["email"], email=attrs["email"])
        try:
            validate_password(attrs["password"], candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": error.messages})

    def create(self, validated_data):
        """Create the inactive account for the given email address."""
        return User.objects.create_user(
            username=validated_data["email"],
            email=validated_data["email"],
            password=validated_data["password"],
            is_active=False,
        )

    def to_representation(self, instance):
        """Return the created account and its activation token."""
        return {
            "user": {"id": instance.pk, "email": instance.email},
            "token": activation_token_generator.make_token(instance),
        }
