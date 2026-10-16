from django.http import HttpResponseNotFound


class NoIndexMiddleware:
    """Keep personal meeting pages out of search engines."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response


def disabled_admin(request, *args, **kwargs):
    """Django admin is unused (accounts are managed at /users/)."""
    return HttpResponseNotFound()
