from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse


class ThemeTests(TestCase):
    """Dark mode is a template contract: keep the toggle and theme hooks from
    drifting off the shared base template."""

    def setUp(self):
        self.user = User.objects.create_superuser('themeuser', 'theme@example.com', 'Theme-Pass-9182')
        self.client.force_login(self.user)

    def _html(self, url_name):
        resp = self.client.get(reverse(url_name))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_base_sets_theme_before_stylesheet(self):
        html = self._html('meeting_list')
        self.assertIn("localStorage.getItem('mr-theme')", html)
        self.assertIn("data-bs-theme", html)
        # the theme script must come before the Bootstrap stylesheet link
        self.assertLess(html.index("localStorage.getItem('mr-theme')"),
                        html.index('bootstrap@5.3.3/dist/css/bootstrap.min.css'))

    def test_toggle_present_on_every_page(self):
        for name in ('meeting_list', 'meeting_new', 'user_list'):
            with self.subTest(page=name):
                html = self._html(name)
                self.assertIn('id="themeToggle"', html)
                self.assertIn("localStorage.setItem('mr-theme'", html)

    def test_no_hardcoded_light_surfaces(self):
        self.assertNotIn('class="bg-light"', self._html('meeting_list'))
        html = self._html('meeting_new')
        self.assertNotIn('bg-white', html)
        self.assertIn('bg-body-tertiary', html)

    def test_toggle_visible_to_logged_out_visitors(self):
        self.client.logout()
        html = self.client.get(reverse('login')).content.decode()
        self.assertIn('id="themeToggle"', html)
