"""Tests for the WSGI and ASGI entry points of the project."""

import io

from django.core.handlers.asgi import ASGIHandler
from django.test import TestCase

from core import asgi, wsgi

ADMIN_LOGIN_PATH = "/admin/login/"


def build_environ(path):
    """Return a minimal WSGI environ for a GET of the given path."""
    return {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.url_scheme": "http",
    }


class WSGIApplicationTests(TestCase):
    """What core.wsgi answers when a WSGI server calls it."""

    def setUp(self):
        """Call the application on the admin login page."""
        self.status = None
        self.response = wsgi.application(
            build_environ(ADMIN_LOGIN_PATH), self.record_status
        )
        self.addCleanup(self.response.close)

    def record_status(self, status, headers, exc_info=None):
        """Store the status line the application reports."""
        self.status = status

    def test_the_application_reports_the_status_of_the_page(self):
        """Calling the application invokes start_response with 200."""
        self.assertEqual(self.status, "200 OK")

    def test_the_returned_iterable_yields_the_page_body(self):
        """Consuming what the application returns yields bytes."""
        self.assertIn(b"<form", b"".join(self.response))


class ASGIApplicationTests(TestCase):
    """What core.asgi exposes to an ASGI server."""

    def test_the_module_imports_and_yields_an_asgi_handler(self):
        """Importing core.asgi yields Django's ASGI handler."""
        self.assertIsInstance(asgi.application, ASGIHandler)
