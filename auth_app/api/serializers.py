"""Serializers of the authentication API."""

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from auth_app.tokens import activation_token_generator

EMAIL_TAKEN_MESSAGE = "This email address is already registered."
PASSWORD_MISMATCH_MESSAGE = "The passwords do not match."


def validate_password_strength(password, user, field):
    """Raise the field errors Django's validators produce."""
    try:
        validate_password(password, user)
    except DjangoValidationError as error:
        raise serializers.ValidationError({field: error.messages})


class NormalizedEmailField(serializers.EmailField):
    """Email field that lowercases the whole address."""

    def to_internal_value(self, data):
        """Return the normalized address."""
        address = super().to_internal_value(data)
        return User.objects.normalize_email(address).lower()


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
        candidate = User(username=attrs["email"], email=attrs["email"])
        validate_password_strength(attrs["password"], candidate, "password")
        return attrs

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


class PasswordResetSerializer(serializers.Serializer):
    """Serializer that reads the address a reset request names."""

    email = NormalizedEmailField()


class PasswordConfirmSerializer(serializers.Serializer):
    """Serializer that sets a new password on the given account."""

    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        """Reject a wrong confirmation or a password Django rejects."""
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": PASSWORD_MISMATCH_MESSAGE}
            )
        validate_password_strength(
            attrs["new_password"], self.instance, "new_password"
        )
        return attrs

    def update(self, instance, validated_data):
        """Store the new password and activate the account."""
        instance.set_password(validated_data["new_password"])
        instance.is_active = True
        instance.save(update_fields=["password", "is_active"])
        return instance


class LoginSerializer(TokenObtainPairSerializer):
    """Serializer that authenticates an account by email address."""

    def __init__(self, *args, **kwargs):
        """Take the email address in place of the username."""
        super().__init__(*args, **kwargs)
        del self.fields[self.username_field]
        self.fields["email"] = NormalizedEmailField(write_only=True)

    def validate(self, attrs):
        """Authenticate the address and describe the account."""
        attrs[self.username_field] = attrs["email"]
        data = super().validate(attrs)
        data["user"] = {"id": self.user.pk, "username": self.user.username}
        return data
