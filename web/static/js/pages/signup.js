import { auth, ApiError } from '../api.js';
import { $, currentUser, renderLayout, safeNext, setTitle } from '../ui.js';

// Те же правила, что в домене (internal/core/domain/user.go): проверяем заранее,
// чтобы показать ошибку у каждого поля, а не только первую от сервера.
const USERNAME_RE = /^[A-Za-z0-9_]{3,30}$/;
const EMAIL_RE = /^[a-z0-9._+-]+@([a-z0-9-]+\.)+[a-z]{2,}$/;
// Печатные ASCII-символы без пробела (0x21–0x7E): латиница, цифры и знаки. Длина 8–72 (лимит bcrypt).
const PASSWORD_RE = /^[\x21-\x7E]{8,72}$/;

const USERNAME_HINT = 'От 3 до 30 символов: латинские буквы, цифры и _.';
const USERNAME_ERROR = USERNAME_HINT;
const EMAIL_ERROR = 'Введите email в формате name@example.com.';
const PASSWORD_HINT = 'От 8 до 72 символов: латинские буквы, цифры и символы, без пробелов.';
const PASSWORD_ERROR = PASSWORD_HINT;
const PASSWORD_SAME_ERROR = 'Пароль не должен совпадать с именем пользователя.';
const USERNAME_TAKEN_ERROR = 'Это имя уже занято. Выберите другое.';
const EMAIL_TAKEN_ERROR = 'Этот email уже зарегистрирован. Попробуйте войти.';
const CONFLICT_ERROR = 'Имя пользователя или email уже заняты.';
const INVALID_ERROR = 'Проверьте имя пользователя, email и пароль.';
const TOO_MANY_ERROR = 'Слишком много попыток. Подождите немного и попробуйте снова.';
const UNKNOWN_ERROR = 'Не удалось создать аккаунт. Попробуйте ещё раз чуть позже.';
const INVITE_ERROR = 'Неверный код приглашения. Код выдаёт администратор сервиса.';

renderLayout({ nav: 'signup' });
setTitle('Регистрация');

const form = $('#signup-form');
const alertBox = $('#signup-alert');
const username = $('#signup-username');
const email = $('#signup-email');
const password = $('#signup-password');
const invite = $('#signup-invite');
const usernameHint = $('#signup-username-hint');
const emailHint = $('#signup-email-hint');
const passwordHint = $('#signup-password-hint');

// Куда вести после регистрации: ?next=/reviews/3 (только путь на этом сайте) или на главную.
const next = new URLSearchParams(location.search).get('next');

// Ссылка «Войти» под формой тоже передаёт next дальше.
const loginLink = document.querySelector('.form__footnote a[href="/login"]');
if (loginLink && next) loginLink.href = '/login?next=' + encodeURIComponent(next);

// Уже вошли — регистрироваться не нужно.
currentUser().then((user) => {
  if (user) location.replace(safeNext(next, '/'));
});

function setFieldError(input, hint, message, defaultText = '') {
  input.toggleAttribute('aria-invalid', Boolean(message));
  hint.textContent = message || defaultText;
  hint.className = message ? 'form__error' : 'form__hint';
  hint.hidden = !message && !defaultText;
}

function showAlert(message) {
  alertBox.textContent = message;
  alertBox.hidden = !message;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  showAlert('');

  const name = username.value.trim();
  const mail = email.value.trim().toLowerCase();
  username.value = name;
  email.value = mail;

  // пароль не обрезаем и не меняем: пробел в нём — ошибка, а не повод его «починить»
  const pass = password.value;
  const usernameOK = USERNAME_RE.test(name);
  const emailOK = mail.length <= 254 && EMAIL_RE.test(mail);
  const passwordFormatOK = PASSWORD_RE.test(pass);
  const passwordSameOK = pass.toLowerCase() !== name.toLowerCase();
  const passwordOK = passwordFormatOK && passwordSameOK;
  setFieldError(username, usernameHint, usernameOK ? '' : USERNAME_ERROR, USERNAME_HINT);
  setFieldError(email, emailHint, emailOK ? '' : EMAIL_ERROR);
  setFieldError(password, passwordHint, passwordOK ? '' : passwordFormatOK ? PASSWORD_SAME_ERROR : PASSWORD_ERROR, PASSWORD_HINT);
  if (!usernameOK || !emailOK || !passwordOK) {
    (!usernameOK ? username : !emailOK ? email : password).focus();
    return;
  }

  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await auth.register(name, mail, pass, invite.value.trim());
    location.href = safeNext(next, '/');
  } catch (err) {
    const status = err instanceof ApiError ? err.status : 0;
    if (status === 409 && err.detail.includes('is already taken')) {
      setFieldError(username, usernameHint, USERNAME_TAKEN_ERROR, USERNAME_HINT);
      username.focus();
    } else if (status === 409 && err.detail.includes('is already registered')) {
      setFieldError(email, emailHint, EMAIL_TAKEN_ERROR);
      email.focus();
    } else {
      showAlert(status === 403 ? INVITE_ERROR : status === 409 ? CONFLICT_ERROR : status === 400 ? INVALID_ERROR : status === 429 ? TOO_MANY_ERROR : UNKNOWN_ERROR);
    }
    password.value = '';
    button.disabled = false;
  }
});
