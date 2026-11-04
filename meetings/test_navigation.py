from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse


class NavigationTests(TestCase):
    """Every page must offer a way back to the signed-in user's meeting list."""

    def setUp(self):
        self.user = User.objects.create_user('navuser', password='Nav-Pass-3311')
        self.client.force_login(self.user)

    def test_nav_has_my_meetings_link(self):
        home = reverse('meeting_list')
        for name in ('meeting_list', 'meeting_new'):
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertIn('href="%s">My meetings</a>' % home, html)

    def test_brand_links_home(self):
        html = self.client.get(reverse('meeting_new')).content.decode()
        self.assertIn('<a class="navbar-brand" href="%s">' % reverse('meeting_list'), html)
