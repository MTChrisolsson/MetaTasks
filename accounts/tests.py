from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser
from core.models import UserProfile


class RegistrationFlowTests(TestCase):
	def test_personal_registration_logs_user_in(self):
		response = self.client.post(
			reverse('accounts:personal_register'),
			{
				'first_name': 'Alice',
				'last_name': 'Example',
				'email': 'alice@example.com',
				'phone_number': '',
				'username': 'AliceUser',
				'password1': 'ComplexPass123!',
				'password2': 'ComplexPass123!',
				'referral_source': '',
				'privacy_policy_accepted': 'on',
				'terms_accepted': 'on',
			},
		)

		self.assertRedirects(response, reverse('homepage:index'), fetch_redirect_response=False)
		self.assertIn('_auth_user_id', self.client.session)

		profile = UserProfile.objects.select_related('organization', 'user').get(user__username='aliceuser')
		self.assertEqual(profile.organization.organization_type, 'personal')
		self.assertTrue(profile.is_organization_admin)

	def test_business_registration_logs_user_in(self):
		response = self.client.post(
			reverse('accounts:business_register'),
			{
				'first_name': 'Bob',
				'last_name': 'Owner',
				'email': 'bob@example.com',
				'phone_number': '',
				'job_title': 'Founder',
				'team_size': '2-10',
				'username': 'BobOwner',
				'password1': 'ComplexPass123!',
				'password2': 'ComplexPass123!',
				'referral_source': '',
				'privacy_policy_accepted': 'on',
				'terms_accepted': 'on',
			},
		)

		self.assertRedirects(response, reverse('accounts:create_organization'), fetch_redirect_response=False)
		self.assertIn('_auth_user_id', self.client.session)
		self.assertEqual(self.client.session.get('account_type'), 'business')
		self.assertEqual(self.client.session.get('registration_step'), 'organization')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetFlowTests(TestCase):
	def test_password_reset_request_sends_email(self):
		CustomUser.objects.create_user(
			username='resetuser',
			email='reset@example.com',
			password='ComplexPass123!',
			first_name='Reset',
			last_name='User',
		)

		response = self.client.post(
			reverse('accounts:password_reset'),
			{'email': 'reset@example.com'},
		)

		self.assertRedirects(response, reverse('accounts:password_reset_done'), fetch_redirect_response=False)
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn('reset@example.com', mail.outbox[0].to)
		self.assertIn('/accounts/reset/', mail.outbox[0].body)

