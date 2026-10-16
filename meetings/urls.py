from django.contrib import admin
from django.urls import path
from . import views
from .password_views import change_password

urlpatterns = [
    path("meetings/<int:pk>/speakers/", views.name_speakers, name="name_speakers"),
    path("", views.meeting_list, name="meeting_list"),
    path("accounts/password/", change_password, name="change_password"),
    path("meetings/new/", views.meeting_new, name="meeting_new"),
    path("users/", views.user_list, name="user_list"),
    path("users/create/", views.user_create, name="user_create"),
    path("users/<int:pk>/password/", views.user_set_password, name="user_set_password"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("meetings/<int:pk>/", views.meeting_detail, name="meeting_detail"),
    path("meetings/<int:pk>/note/", views.add_note, name="add_note"),
    path("meetings/<int:pk>/summarize/", views.do_summary, name="do_summary"),
    path("meetings/<int:pk>/delete/", views.delete_meeting, name="delete_meeting"),
    path("meetings/<int:pk>/live-chunk/", views.live_chunk, name="live_chunk"),
    path("meetings/<int:pk>/live/", views.live_segments, name="live_segments"),
    path("meetings/<int:pk>/download.<str:fmt>", views.download_transcript, name="download_transcript"),
    path("meetings/<int:pk>/gdrive/", views.send_to_gdrive, name="send_to_gdrive"),
]
