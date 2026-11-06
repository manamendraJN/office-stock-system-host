/* Login-only progressive enhancements. Authentication remains a normal form post. */
(function () {
  'use strict';
  var form = document.querySelector('.login-layout');
  var toggle = document.querySelector('[data-password-toggle]');
  var password = document.querySelector('.password-field-control input');
  var submit = document.querySelector('[data-login-submit]');

  if (toggle && password) {
    toggle.addEventListener('click', function () {
      var shown = password.type === 'text';
      password.type = shown ? 'password' : 'text';
      toggle.setAttribute('aria-label', shown ? 'Show password' : 'Hide password');
      toggle.setAttribute('aria-pressed', String(!shown));
      password.focus();
    });
  }

  if (form && submit) {
    form.addEventListener('submit', function () {
      if (!form.checkValidity || form.checkValidity()) {
        submit.disabled = true;
        submit.setAttribute('aria-busy', 'true');
        var label = submit.querySelector('.login-submit-label');
        if (label) label.textContent = 'Signing in…';
      }
    });
  }
}());
