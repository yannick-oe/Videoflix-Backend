"""Views of the video API."""

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from video_app.api.serializers import VideoSerializer
from video_app.models import Video


class VideoListView(generics.ListAPIView):
    """List every video the catalogue holds."""

    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    permission_classes = [IsAuthenticated]
