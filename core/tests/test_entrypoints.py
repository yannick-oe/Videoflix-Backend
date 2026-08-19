"""Tests for the WSGI and ASGI entry points of the project."""

from django.test import TestCase

from core import asgi, wsgi


class EntryPointTests(TestCase):
    """The application objects the servers import on start."""

    def test_the_wsgi_module_exposes_an_application(self):
        """Importing core.wsgi yields an application object."""
        self.assertIsNotNone(wsgi.application)

    def test_the_wsgi_application_is_callable(self):
        """A WSGI server can call what the module exposes."""
        self.assertTrue(callable(wsgi.application))

    def test_the_asgi_module_exposes_an_application(self):
        """Importing core.asgi yields an application object."""
        self.assertIsNotNone(asgi.application)

    def test_the_asgi_application_is_callable(self):
        """An ASGI server can call what the module exposes."""
        self.assertTrue(callable(asgi.application))
