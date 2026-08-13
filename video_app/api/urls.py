"""URL routes of the video API."""

import re

from django.urls import path, re_path

from video_app.api.views import ManifestView, SegmentView, VideoListView
from video_app.services.conversion import PLAYLIST_NAME, RENDITIONS

MOVIE_ID = r"(?P<movie_id>[0-9]+)"
RESOLUTION = rf"(?P<resolution>{'|'.join(RENDITIONS)})"
SEGMENT = r"(?P<segment>[0-9]+\.ts)"
RENDITION_ROUTE = rf"^video/{MOVIE_ID}/{RESOLUTION}/"
MANIFEST_ROUTE = rf"{RENDITION_ROUTE}{re.escape(PLAYLIST_NAME)}$"
SEGMENT_ROUTE = rf"{RENDITION_ROUTE}{SEGMENT}"

urlpatterns = [
    path("video/", VideoListView.as_view(), name="video-list"),
    re_path(MANIFEST_ROUTE, ManifestView.as_view(), name="video-manifest"),
    re_path(
        f"{SEGMENT_ROUTE}/$",
        SegmentView.as_view(),
        name="video-segment",
    ),
    re_path(
        f"{SEGMENT_ROUTE}$",
        SegmentView.as_view(),
        name="video-segment-bare",
    ),
]
