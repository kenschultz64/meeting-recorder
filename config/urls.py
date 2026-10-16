"""URL configuration for the meeting recorder."""
from meetings.middleware import disabled_admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", disabled_admin),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("meetings.urls")),
]

from meetings.views import docs_guide, private_audio
urlpatterns += [
    path("docs/guide.pdf", docs_guide, name="docs_guide"),
    path("media/<path:name>", private_audio, name="private_audio"),
]
