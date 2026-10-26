from django.test import SimpleTestCase

from accounts.forms import ChangePasswordForm, ResetPasswordForm, UserForm


class PasswordFormSecurityTests(SimpleTestCase):
    def test_password_inputs_do_not_render_plaintext(self):
        self.assertEqual(UserForm().fields['password'].widget.input_type, 'password')
        self.assertEqual(ResetPasswordForm().fields['password'].widget.input_type, 'password')

    def test_change_password_rejects_numeric_only_password(self):
        form = ChangePasswordForm(data={
            'current_password': 'current-password',
            'new_password': '123456789012',
            'confirm': '123456789012',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('new_password', form.errors)

    def test_reset_password_accepts_a_long_noncommon_password(self):
        form = ResetPasswordForm(data={'password': 'Blue-Lantern!Meadow82'})
        self.assertTrue(form.is_valid(), form.errors)
