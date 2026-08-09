"""Tests for the password confirmation endpoint."""

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from auth_app.api.views import (
    PASSWORD_CONFIRM_FAILURE_MESSAGE,
    PASSWORD_CONFIRM_SUCCESS_MESSAGE,
)

EMAIL = "user@example.com"
OTHER_EMAIL = "stranger@example.com"
PASSWORD = "securepassword"
NEW_PASSWORD = "brandnewpassword"
REPLAY_PASSWORD = "yetanotherpassword"
WEAK_PASSWORD = "12345678"
UNKNOWN_UID = urlsafe_base64_encode(force_bytes(9999))
MALFORMED_UID = "not-base64!!"
GARBAGE_TOKEN = "abc-def"
DOCUMENTED_BODY = b'{"detail":"Your Password has been successfully reset."}'


def uid_of(user):
    """Return the base64 encoded id of the given account."""
    return urlsafe_base64_encode(force_bytes(user.pk))


class ConfirmTestCase(TestCase):
    """Shared account, link and requests of the confirmation tests."""

    def setUp(self):
        """Create the account and mint the token of its reset link."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        self.token = default_token_generator.make_token(self.user)

    def confirm(self, payload, uidb64=None, token=None):
        """Post the payload against the confirmation endpoint."""
        url = reverse(
            "password-confirm",
            kwargs={
                "uidb64": uidb64 or uid_of(self.user),
                "token": token or self.token,
            },
        )
        return self.client.post(url, payload, content_type="application/json")

    def reset(self, password=NEW_PASSWORD, **parts):
        """Confirm the link with a matching pair of passwords."""
        payload = {
            "new_password": password,
            "confirm_password": password,
        }
        return self.confirm(payload, **parts)

    def log_in(self, password):
        """Return the status of a login with the given password."""
        return self.client.post(
            reverse("login"),
            {"email": EMAIL, "password": password},
            content_type="application/json",
        ).status_code

    def assert_rejected(self, response):
        """Assert the shared answer to an unusable reset link."""
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"detail": PASSWORD_CONFIRM_FAILURE_MESSAGE}
        )


class ConfirmSuccessTests(ConfirmTestCase):
    """A usable link with a matching pair resets the password."""

    def test_usable_link_is_confirmed(self):
        """A usable link is answered with 200."""
        self.assertEqual(self.reset().status_code, 200)

    def test_answer_is_the_documented_body(self):
        """The rendered body is the JSON of the documentation."""
        self.assertEqual(self.reset().content, DOCUMENTED_BODY)

    def test_message_is_the_documented_text(self):
        """The confirmation is the text of the documentation."""
        self.assertEqual(
            PASSWORD_CONFIRM_SUCCESS_MESSAGE,
            "Your Password has been successfully reset.",
        )

    def test_new_password_logs_the_account_in(self):
        """The account logs in with the password it just set."""
        self.reset()
        self.assertEqual(self.log_in(NEW_PASSWORD), 200)

    def test_old_password_no_longer_logs_in(self):
        """The password the reset replaced is turned away."""
        self.reset()
        self.assertEqual(self.log_in(PASSWORD), 401)

    def test_password_is_stored_hashed(self):
        """The new password never reaches the column in clear text."""
        self.reset()
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.password, NEW_PASSWORD)
        self.assertTrue(self.user.check_password(NEW_PASSWORD))


class ConfirmActivationTests(ConfirmTestCase):
    """A reset certifies the address of an account never activated."""

    def setUp(self):
        """Deactivate the account and mint a token for that state."""
        super().setUp()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.token = default_token_generator.make_token(self.user)

    def test_account_cannot_log_in_beforehand(self):
        """The account is turned away before it is reset."""
        self.assertEqual(self.log_in(PASSWORD), 401)

    def test_account_is_active_afterwards(self):
        """The reset leaves the account activated."""
        self.reset()
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_account_can_log_in_afterwards(self):
        """The activated account logs in with its new password."""
        self.reset()
        self.assertEqual(self.log_in(NEW_PASSWORD), 200)

    def test_refused_pair_leaves_the_account_inactive(self):
        """A password the validators refuse activates nothing."""
        self.reset(WEAK_PASSWORD)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_unusable_link_leaves_the_account_inactive(self):
        """A link that does not check out activates nothing."""
        self.reset(token=GARBAGE_TOKEN)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)


class ConfirmTokenTests(ConfirmTestCase):
    """The token dies with the password hash it was minted from."""

    def test_second_use_of_the_link_is_rejected(self):
        """The link of a completed reset does not work twice."""
        self.assertEqual(self.reset().status_code, 200)
        self.assert_rejected(self.reset(REPLAY_PASSWORD))

    def test_replay_does_not_change_the_password(self):
        """The password of a completed reset survives a replay."""
        self.reset()
        self.reset(REPLAY_PASSWORD)
        self.assertEqual(self.log_in(NEW_PASSWORD), 200)

    def test_unrelated_password_change_kills_the_token(self):
        """A password set elsewhere invalidates a minted token."""
        self.user.set_password(REPLAY_PASSWORD)
        self.user.save(update_fields=["password"])
        self.assert_rejected(self.reset())

    def test_token_of_another_account_is_rejected(self):
        """A token minted for a second account is turned away."""
        other = User.objects.create_user(
            username=OTHER_EMAIL, email=OTHER_EMAIL, password=PASSWORD
        )
        token = default_token_generator.make_token(other)
        self.assert_rejected(self.reset(token=token))


class ConfirmLinkTests(ConfirmTestCase):
    """Every unusable link is answered the same way."""

    def bodies(self):
        """Return the raw answer to each of the four bad links."""
        other = User.objects.create_user(
            username=OTHER_EMAIL, email=OTHER_EMAIL, password=PASSWORD
        )
        parts = [
            {"uidb64": MALFORMED_UID},
            {"uidb64": UNKNOWN_UID},
            {"token": GARBAGE_TOKEN},
            {"token": default_token_generator.make_token(other)},
        ]
        return [self.reset(**part).content for part in parts]

    def test_malformed_uid_is_rejected(self):
        """A uid that is no base64 string is turned away."""
        self.assert_rejected(self.reset(uidb64=MALFORMED_UID))

    def test_uid_without_an_account_is_rejected(self):
        """A uid that decodes to no account is turned away."""
        self.assert_rejected(self.reset(uidb64=UNKNOWN_UID))

    def test_garbage_token_is_rejected(self):
        """A token that was never minted is turned away."""
        self.assert_rejected(self.reset(token=GARBAGE_TOKEN))

    def test_all_bad_links_are_byte_identical(self):
        """No bad link reveals which of its parts was wrong."""
        self.assertEqual(len(set(self.bodies())), 1)

    def test_bad_link_leaves_the_password_alone(self):
        """A link that does not check out changes nothing."""
        self.reset(uidb64=UNKNOWN_UID)
        self.assertEqual(self.log_in(PASSWORD), 200)


class ConfirmBodyTests(ConfirmTestCase):
    """A usable link still needs a pair the validators accept."""

    def test_mismatched_pair_is_rejected(self):
        """A confirmation that differs is answered with 400."""
        response = self.confirm(
            {"new_password": NEW_PASSWORD, "confirm_password": PASSWORD}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirm_password", response.json())

    def test_weak_password_is_rejected(self):
        """A password Django's validators refuse is answered 400."""
        response = self.reset(WEAK_PASSWORD)
        self.assertEqual(response.status_code, 400)
        self.assertIn("new_password", response.json())

    def test_password_like_the_address_is_rejected(self):
        """The account reaches the validators that compare it."""
        response = self.reset(EMAIL)
        self.assertEqual(response.status_code, 400)
        self.assertIn("new_password", response.json())

    def test_missing_new_password_is_rejected(self):
        """A body without the new password is answered with 400."""
        response = self.confirm({"confirm_password": NEW_PASSWORD})
        self.assertEqual(response.status_code, 400)
        self.assertIn("new_password", response.json())

    def test_missing_confirmation_is_rejected(self):
        """A body without the confirmation is answered with 400."""
        response = self.confirm({"new_password": NEW_PASSWORD})
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirm_password", response.json())

    def test_empty_body_is_rejected(self):
        """A body without either field is answered with 400."""
        response = self.confirm({})
        self.assertEqual(response.status_code, 400)
        self.assertIn("new_password", response.json())
        self.assertIn("confirm_password", response.json())

    def test_refused_pair_leaves_the_password_alone(self):
        """A pair the validators refuse changes nothing."""
        self.reset(WEAK_PASSWORD)
        self.assertEqual(self.log_in(PASSWORD), 200)

    def test_refused_pair_leaves_the_link_usable(self):
        """A refused pair does not spend the reset link."""
        self.reset(WEAK_PASSWORD)
        self.assertEqual(self.reset().status_code, 200)
