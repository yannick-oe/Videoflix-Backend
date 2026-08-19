"""Tests for the extensions the two file fields accept."""

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import modelform_factory
from django.test import TestCase

from video_app.models import Video

TITLE = "Movie Title"
DESCRIPTION = "Movie Description"
CATEGORY = "Drama"
SOURCE_NAME = "videos/clip.mp4"
FRAME_NAME = "thumbnails/cover.jpg"
UPPERCASE_SOURCE = "videos/clip.MOV"
UPPERCASE_FRAME = "thumbnails/cover.JPG"
UNPLAYABLE_SOURCE = "videos/handbook.pdf"
UNRENDERABLE_FRAME = "thumbnails/IMG_1931.HEIC"
SOURCE_UPLOAD = "clip.mp4"
FRAME_UPLOAD = "IMG_1931.HEIC"
RENDERABLE_UPLOAD = "cover.jpg"
UPLOAD_CONTENT = b"upload bytes"
FORM_FIELDS = ["title", "description", "category", "video_file", "thumbnail"]
REJECTED_EXTENSION = "heic"
ALLOWED_FRAME_EXTENSION = "jpg"


def build(source=SOURCE_NAME, frame=FRAME_NAME):
    """Return an unsaved video carrying these two file names."""
    return Video(
        title=TITLE,
        description=DESCRIPTION,
        category=CATEGORY,
        video_file=source,
        thumbnail=frame,
    )


def field_errors(video):
    """Return the field errors a full check finds on this video."""
    try:
        video.full_clean()
    except ValidationError as error:
        return error.message_dict
    return {}


class AcceptedUploadTests(TestCase):
    """Names the two file fields let through unchanged."""

    def test_a_named_source_and_frame_pass(self):
        """The extensions the pipeline produces raise nothing."""
        self.assertEqual(field_errors(build()), {})

    def test_the_extensions_are_matched_without_case(self):
        """An upload named in capitals passes just as well."""
        video = build(source=UPPERCASE_SOURCE, frame=UPPERCASE_FRAME)
        self.assertEqual(field_errors(video), {})

    def test_a_video_without_a_frame_passes(self):
        """A row still waiting for its thumbnail raises nothing."""
        self.assertEqual(field_errors(build(frame="")), {})


class RejectedUploadTests(TestCase):
    """Names the two file fields refuse to take."""

    def test_an_unrenderable_frame_is_refused(self):
        """A thumbnail no browser renders is named as the fault."""
        video = build(frame=UNRENDERABLE_FRAME)
        self.assertIn("thumbnail", field_errors(video))

    def test_an_unplayable_source_is_refused(self):
        """A source no player reads is named as the fault."""
        video = build(source=UNPLAYABLE_SOURCE)
        self.assertIn("video_file", field_errors(video))

    def test_the_message_names_the_refused_extension(self):
        """The admin is told which extension was turned away."""
        errors = field_errors(build(frame=UNRENDERABLE_FRAME))
        self.assertIn(REJECTED_EXTENSION, errors["thumbnail"][0])

    def test_the_message_names_an_extension_that_works(self):
        """The admin is told which extension works."""
        errors = field_errors(build(frame=UNRENDERABLE_FRAME))
        self.assertIn(ALLOWED_FRAME_EXTENSION, errors["thumbnail"][0])


class AdminFormTests(TestCase):
    """The form behind the admin carries the same refusal."""

    def form(self, frame):
        """Return the bound admin form for an upload of this frame."""
        form_class = modelform_factory(Video, fields=FORM_FIELDS)
        return form_class(
            {
                "title": TITLE,
                "description": DESCRIPTION,
                "category": CATEGORY,
            },
            {
                "video_file": SimpleUploadedFile(
                    SOURCE_UPLOAD, UPLOAD_CONTENT
                ),
                "thumbnail": SimpleUploadedFile(frame, UPLOAD_CONTENT),
            },
        )

    def test_the_form_reports_the_refused_frame(self):
        """The admin form refuses the thumbnail by its extension."""
        self.assertIn("thumbnail", self.form(FRAME_UPLOAD).errors)

    def test_the_form_takes_a_frame_it_can_render(self):
        """The admin form lets a renderable thumbnail through."""
        self.assertNotIn("thumbnail", self.form(RENDERABLE_UPLOAD).errors)


class StoredWriteTests(TestCase):
    """Writes the pipeline makes itself reach storage unchecked."""

    def test_a_stored_write_is_not_validated(self):
        """A save the worker performs runs no field validator."""
        video = Video.objects.create(
            title=TITLE,
            description=DESCRIPTION,
            category=CATEGORY,
            video_file=SOURCE_NAME,
            thumbnail=UNRENDERABLE_FRAME,
        )
        self.assertEqual(video.thumbnail.name, UNRENDERABLE_FRAME)
