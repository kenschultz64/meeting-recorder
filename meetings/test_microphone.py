from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

class MicrophoneSetupTests(TestCase):
    def test_setup_controls_available_to_owner(self):
        user = User.objects.create_user(username='mic-unit')
        self.client.force_login(user)
        response = self.client.get(reverse('meeting_new'))
        for text in ['id="micSelect"', 'id="micLevel"', 'id="micTest"', 'id="micTestPreview"', 'Nothing was uploaded.', 'micSetup.capture()', 'micSetup.lock(true)']:
            self.assertContains(response, text)
    def test_new_meeting_requires_login(self):
        self.assertEqual(self.client.get(reverse('meeting_new')).status_code, 302)
