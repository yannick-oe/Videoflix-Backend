"""Background jobs of the video app."""

from video_app.models import Video
from video_app.services.conversion import create_rendition
from video_app.services.thumbnail import create_thumbnail


def generate_thumbnail(video_id):
    """Store the preview frame of the video this id addresses."""
    video = Video.objects.filter(pk=video_id).first()
    if video is None:
        return
    create_thumbnail(video)


def generate_rendition(video_id, resolution):
    """Store one HLS rendition of the video this id addresses."""
    video = Video.objects.filter(pk=video_id).first()
    if video is None:
        return
    create_rendition(video, resolution)
