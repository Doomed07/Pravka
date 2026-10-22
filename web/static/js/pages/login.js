import { auth, ApiError } from '../api.js';
import { $, currentUser, renderLayout, safeNext, setTitle } from '../ui.js';

const EMPTY_ERROR = 'Введите имя пользователя или email и пароль.';
const WRONG_ERROR = 'Неверное имя пользователя, email или пароль.';
const INVALID_ERROR = 'Проверьте введённые данные.';
const TOO_MANY_ERROR = 'Слишком много попыток. Подождите немного и попробуйте снова.';
const UNKNOWN_ERROR = 'Не удалось войти. Попробуйте ещё раз чуть позже.';

renderLayout({ nav: 'login' });
setTitle('Вход');

const form = $('#login-form');
const alertBox = $('#login-alert');
const login = $('#login-login');
const password = $('#login-password');

// Куда вести после входа: ?next=/reviews/3 (только путь на этом сайте) или на главную.
const next = new URLSearchParams(location.search).get('next');

function showAlert(message) {
  alertBox.textContent = message;
  alertBox.hidden = !message;
}

// Уже вошли — форма не нужна.
currentUser().then((user) => {
  if (user) location.replace(safeNext(next, '/'));
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  showAlert('');

  const name = login.value.trim();
  login.value = name;
  const passwordMissing = password.value === '';
  login.toggleAttribute('aria-invalid', name === '');
  password.toggleAttribute('aria-invalid', passwordMissing);
  if (name === '' || passwordMissing) {
    showAlert(EMPTY_ERROR);
    (name === '' ? login : password).focus();
    return;
  }

  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await auth.login(name, password.value);
    location.href = safeNext(next, '/');
  } catch (err) {
    const status = err instanceof ApiError ? err.status : 0;
    showAlert(status === 401 ? WRONG_ERROR : status === 400 ? INVALID_ERROR : status === 429 ? TOO_MANY_ERROR : UNKNOWN_ERROR);
    password.value = '';
    password.focus();
    button.disabled = false;
  }
});
