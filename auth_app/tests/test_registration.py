"""Tests for the registration endpoint."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from auth_app.tokens import activation_token_generator

EMAIL = "user@example.com"
PASSWORD = "securepassword"
PAYLOAD = {
    "email": EMAIL,
    "password": PASSWORD,
    "confirmed_password": PASSWORD,
}


class RegistrationTests(TestCase):
    """Behaviour of POST /api/register/ as seen by a client."""

    def setUp(self):
        """Store the endpoint URL."""
        self.url = reverse("register")

    def register(self, **changes):
        """Post the sample payload with the given fields changed."""
        return self.client.post(
            self.url, PAYLOAD | changes, content_type="application/json"
        )

    def test_valid_payload_is_accepted(self):
        """A complete payload answers 201."""
        self.assertEqual(self.register().status_code, 201)

    def test_response_body_matches_the_contract(self):
        """The body carries the new account and an activation token."""
        body = self.register().content.decode()
        created = User.objects.get()
        self.assertJSONEqual(
            body,
            {
                "user": {"id": created.pk, "email": EMAIL},
                "token": json.loads(body)["token"],
            },
        )

    def test_response_body_keeps_the_documented_key_order(self):
        """The raw JSON lists user before token and id before email."""
        body = self.register().content.decode()
        self.assertLess(body.index('"user"'), body.index('"token"'))
        self.assertLess(body.index('"id"'), body.index('"email"'))

    def test_new_account_is_inactive(self):
        """Registration alone does not activate the account."""
        self.register()
        self.assertFalse(User.objects.get().is_active)

    def test_username_is_the_email_address(self):
        """The username mirrors the registered email address."""
        self.register()
        self.assertEqual(User.objects.get().username, EMAIL)

    def test_password_is_stored_hashed(self):
        """The stored password is a hash of the submitted one."""
        self.register()
        created = User.objects.get()
        self.assertNotEqual(created.password, PASSWORD)
        self.assertTrue(created.check_password(PASSWORD))

    def test_returned_token_validates_for_the_new_account(self):
        """The returned token belongs to the created account."""
        token = self.register().json()["token"]
        created = User.objects.get()
        self.assertTrue(activation_token_generator.check_token(created, token))

    def test_returned_token_expires_once_the_account_is_active(self):
        """Activating the account invalidates the returned token."""
        token = self.register().json()["token"]
        created = User.objects.get()
        created.is_active = True
        created.save()
        self.assertFalse(
            activation_token_generator.check_token(created, token)
        )

    def test_unknown_fields_are_ignored(self):
        """An extra privacy_policy field does not break the request."""
        response = self.register(privacy_policy="on")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(hasattr(User.objects.get(), "privacy_policy"))

    def test_email_address_is_lowercased(self):
        """The whole address is stored lowercased."""
        self.register(email="User@EXAMPLE.com")
        self.assertEqual(User.objects.get().email, EMAIL)

    def test_known_email_is_rejected_regardless_of_case(self):
        """Addresses differing only in case count as one account."""
        self.assertEqual(
            self.register(email="User@Example.com").status_code, 201
        )
        response = self.register(email="uSeR@example.COM")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json())
        self.assertEqual(User.objects.get().email, EMAIL)

    def test_mismatched_confirmation_is_rejected(self):
        """A wrong confirmation answers 400 with a JSON body."""
        response = self.register(confirmed_password="somethingelse")
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirmed_password", response.json())

    def test_known_email_is_rejected(self):
        """A second registration of the same address answers 400."""
        self.register()
        response = self.register()
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json())

    def test_known_email_is_rejected_regardless_of_domain_case(self):
        """Addresses differing only in domain case count as one."""
        self.register()
        response = self.register(email="user@EXAMPLE.com")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 1)

    def test_malformed_email_is_rejected(self):
        """An address without a domain answers 400."""
        response = self.register(email="not-an-email")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json())

    def test_weak_password_is_rejected(self):
        """A password Django's validators reject answers 400."""
        response = self.register(
            password="12345678", confirmed_password="12345678"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())

    def test_password_similar_to_the_email_is_rejected(self):
        """A password resembling the address answers 400."""
        response = self.register(password=EMAIL, confirmed_password=EMAIL)
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())

    def test_missing_field_is_rejected(self):
        """A payload without a confirmation answers 400."""
        response = self.client.post(
            self.url,
            {"email": EMAIL, "password": PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirmed_password", response.json())

    def test_rejected_payload_creates_no_account(self):
        """A rejected request leaves the database untouched."""
        self.register(confirmed_password="somethingelse")
        self.assertFalse(User.objects.exists())
