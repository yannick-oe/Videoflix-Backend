"""Views of the video API."""

from pathlib import Path

from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils._os import safe_join
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from video_app.api.serializers import VideoSerializer
from video_app.models import Video
from video_app.services.conversion import PLAYLIST_NAME, video_directory

MANIFEST_TYPE = "application/vnd.apple.mpegurl"
SEGMENT_TYPE = "video/MP2T"
NOT_FOUND_MESSAGE = "Video or file not found."


def rendition_file(video_id, resolution, name):
    """Return the path of one file inside a rendition directory."""
    directory = video_directory(video_id) / resolution
    try:
        return Path(safe_join(directory, name))
    except SuspiciousFileOperation as error:
        raise Http404(NOT_FOUND_MESSAGE) from error


def open_rendition_file(movie_id, resolution, name):
    """Open a file of a stored video's rendition for reading."""
    video = get_object_or_404(Video, pk=movie_id)
    try:
        return rendition_file(video.pk, resolution, name).open("rb")
    except OSError as error:
        raise Http404(NOT_FOUND_MESSAGE) from error


class VideoListView(generics.ListAPIView):
    """List every video the catalogue holds."""

    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    permission_classes = [IsAuthenticated]


class RenditionFileView(APIView):
    """Stream one file out of the HLS renditions of a video."""

    permission_classes = [IsAuthenticated]

    def respond_with(self, movie_id, resolution, name):
        """Answer with this file of the addressed rendition."""
        stream = open_rendition_file(movie_id, resolution, name)
        return FileResponse(stream, content_type=self.content_type)


class ManifestView(RenditionFileView):
    """Hand out the HLS playlist of one rendition."""

    content_type = MANIFEST_TYPE

    def get(self, request, movie_id, resolution):
        """Answer with the playlist of the addressed rendition."""
        return self.respond_with(movie_id, resolution, PLAYLIST_NAME)


class SegmentView(RenditionFileView):
    """Hand out one segment of one rendition."""

    content_type = SEGMENT_TYPE

    def get(self, request, movie_id, resolution, segment):
        """Answer with the addressed segment of this rendition."""
        return self.respond_with(movie_id, resolution, segment)
