// Общие куски интерфейса: шапка, подвал, пагинация, ошибки.
//
// Разметка собирается шаблоном html`…`: всё, что подставляется в ${…}, экранируется,
// кроме вложенных html`…`. Поэтому текст из базы (имена файлов, предупреждения) не может стать HTML-кодом.

import { ApiError, auth } from './api.js';

class SafeHTML {
  constructor(value) {
    this.value = value;
  }
}

export function escapeHTML(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderValue(v) {
  if (v === null || v === undefined || v === false) return '';
  if (v instanceof SafeHTML) return v.value;
  if (Array.isArray(v)) return v.map(renderValue).join('');
  return escapeHTML(v);
}

export function html(strings, ...values) {
  let out = strings[0];
  values.forEach((v, i) => {
    out += renderValue(v) + strings[i + 1];
  });
  return new SafeHTML(out);
}

export function mount(element, content) {
  element.innerHTML = renderValue(content);
}

export const $ = (selector) => document.querySelector(selector);

// ---------- Шапка и подвал ----------

const NAV = [
  { key: 'home', href: '/', label: 'Контрагенты' },
  { key: 'about', href: '/about', label: 'О сервисе' },
];

function header({ nav = '', navDetail = false }) {
  const links = NAV.map((item) => {
    const current = item.key === nav ? html` aria-current="${navDetail ? 'true' : 'page'}"` : '';
    return html`<a href="${item.href}"${current}>${item.label}</a>`;
  });

  return html`
    <header class="site-header">
      <div class="container site-header__inner">
        <a class="logo" href="/">
          <span class="logo__mark" aria-hidden="true"></span>
          <span class="logo__word">Правки</span>
        </a>
        <nav class="main-nav" aria-label="Основное меню">${links}</nav>
        <div class="auth-nav" id="auth-nav"></div>
        <button class="theme-toggle" type="button" id="theme-toggle" aria-label="Сменить тему" title="Светлая / тёмная тема"></button>
      </div>
    </header>`;
}

function footer() {
  return html`
    <footer class="site-footer">
      <div class="container site-footer__inner">
        <nav class="footer-nav" aria-label="Ссылки в подвале">
          <a href="/">Контрагенты</a>
          <a href="/about">О сервисе</a>
        </nav>
        <p>Правки — разбор правок контрагента. Решения принимает плейбук, сомнения — юрист.</p>
      </div>
    </footer>`;
}

// ---------- Тема ----------

// Светлая или тёмная тема: выбор запоминается в браузере (если он недоступен — работает по настройке системы).
const THEME_KEY = 'pravki-theme';

function storedTheme() {
  try {
    return localStorage.getItem(THEME_KEY);
  } catch {
    return null;
  }
}

function isDark() {
  const set = document.documentElement.dataset.theme;
  if (set) return set === 'dark';
  return matchMedia('(prefers-color-scheme: dark)').matches;
}

function paintToggle() {
  const button = document.getElementById('theme-toggle');
  if (button) button.textContent = isDark() ? '☀' : '☾';
}

function toggleTheme() {
  const next = isDark() ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {
    /* выбор не запомнится — не страшно */
  }
  paintToggle();
}

if (['light', 'dark'].includes(storedTheme())) document.documentElement.dataset.theme = storedTheme();

// ---------- Аккаунт ----------

let account;

// currentUser — вошедший пользователь ({id, username, email}) или null.
// Запрос к /auth/me делается один раз на страницу; любой сбой считается «не вошёл»,
// чтобы шапка не ломала страницу. Запрос стартует уже при загрузке модуля.
export function currentUser() {
  account ??= auth.me().catch((err) => {
    if (!(err instanceof ApiError)) console.error(err);
    return null;
  });
  return account;
}
currentUser();

function authNav(user, nav) {
  if (!user) {
    const current = (key) => (nav === key ? html` aria-current="page"` : '');
    return html`
      <a class="auth-nav__link" href="/login"${current('login')}>Войти</a>
      <a class="button button--cta auth-nav__cta" href="/signup"${current('signup')}>Регистрация</a>`;
  }
  return html`
    <span class="auth-nav__link auth-nav__user">${user.username}</span>
    <button class="auth-nav__link auth-nav__button" type="button" id="logout-button">Выйти</button>`;
}

async function logout(button) {
  button.disabled = true;
  try {
    await auth.logout();
    location.reload();
  } catch {
    button.disabled = false;
    button.textContent = 'Не вышло. Ещё раз?';
  }
}

function showAccount(user, nav) {
  const slot = $('#auth-nav');
  if (!slot) return;
  mount(slot, authNav(user, nav));
  const button = $('#logout-button');
  if (button) button.addEventListener('click', () => logout(button));
}

// safeNext — адрес для возврата после входа (?next=…). Пускаем только путь на этом же сайте:
// иначе ссылка вида /login?next=//evil.example уводила бы человека на чужой сайт сразу после входа.
export function safeNext(raw, fallback) {
  if (!raw || raw[0] !== '/' || raw[1] === '/' || raw[1] === '\\') return fallback;
  if (/[\u0000-\u001f\u007f]/.test(raw)) return fallback;
  try {
    const url = new URL(raw, location.origin);
    if (url.origin !== location.origin) return fallback;
    if (url.pathname === '/login' || url.pathname === '/signup') return fallback; // не возвращаем на форму входа
    return url.pathname + url.search + url.hash;
  } catch {
    return fallback;
  }
}

// renderLayout вставляет шапку и подвал в #site-header и #site-footer страницы
// и, когда станет известно, кто вошёл, — ссылки аккаунта в шапку.
export function renderLayout(options = {}) {
  mount($('#site-header'), header(options));
  mount($('#site-footer'), footer());
  const toggle = $('#theme-toggle');
  if (toggle) toggle.addEventListener('click', toggleTheme);
  paintToggle();
  currentUser().then((user) => showAccount(user, options.nav));
}

export function setTitle(title) {
  document.title = title ? `${title} · Правки` : 'Правки — разбор правок контрагента';
}

export function emptyState(content) {
  return html`<p class="empty-state">${content}</p>`;
}

export function loading() {
  return html`<p class="loading" role="status">Загрузка…</p>`;
}

// ---------- Параметры адреса и пагинация ----------

export const MAX_PAGE = 10000;

// pageParam — номер страницы из ?page=. Неверное значение — ошибка 400.
export function pageParam() {
  const raw = new URLSearchParams(location.search).get('page');
  if (raw === null || raw === '') return 1;
  const page = Number(raw);
  if (!Number.isInteger(page) || page < 1 || page > MAX_PAGE) throw new ApiError(400, 'invalid page');
  return page;
}

// pathID — id из адреса вида /reviews/3. Неверный id — «нет такой страницы» (404).
export function pathID() {
  const raw = location.pathname.split('/').filter(Boolean).pop();
  const id = Number(raw);
  if (!/^\d+$/.test(raw || '') || id < 1 || id > 2147483647) throw new ApiError(404, 'invalid id');
  return id;
}

// trimPage — приём «limit+1»: просим у API на один элемент больше размера страницы.
// Пришёл лишний — значит, есть следующая страница; сам он не показывается.
export function trimPage(items, size) {
  const list = items || [];
  return list.length > size ? [list.slice(0, size), true] : [list, false];
}

// pageURL меняет только номер страницы, остальные параметры сохраняет.
export function pageURL(page) {
  const params = new URLSearchParams(location.search);
  if (page <= 1) params.delete('page');
  else params.set('page', page);
  params.sort();
  const s = params.toString();
  return location.pathname + (s ? '?' + s : '');
}

export function pagination(page, hasNext) {
  if (page <= 1 && !hasNext) return '';
  return html`
    <nav class="pagination" aria-label="Страницы">
      ${page > 1 ? html`<a class="pagination__link" href="${pageURL(page - 1)}" rel="prev">← Назад</a>` : ''}
      <span class="pagination__current">Страница ${page}</span>
      ${hasNext ? html`<a class="pagination__link" href="${pageURL(page + 1)}" rel="next">Дальше →</a>` : ''}
    </nav>`;
}

// ---------- Ошибки ----------

const ERRORS = {
  400: ['Некорректный запрос', 'Проверьте адрес страницы или параметры фильтра.'],
  401: ['Нужно войти', 'Войдите в аккаунт, чтобы продолжить.'],
  403: ['Недостаточно прав', 'Это действие доступно только владельцу разбора.'],
  404: ['Страница не найдена', 'Возможно, её удалили или в адресе опечатка.'],
  409: ['Конфликт данных', 'Данные изменились, пока вы их смотрели. Обновите страницу.'],
  429: ['Слишком много запросов', 'Подождите немного и попробуйте снова.'],
};

export function errorView(status) {
  if (!document.querySelector('meta[name="robots"]')) {
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex';
    document.head.append(meta);
  }

  const code = ERRORS[status] ? status : 500;
  const [heading, message] = ERRORS[code] || ['Что-то пошло не так', 'Попробуйте обновить страницу чуть позже.'];
  setTitle(heading);
  return html`
    <div class="container page">
      <section class="error-page">
        <p class="error-page__code">${code}</p>
        <h1 class="error-page__title">${heading}</h1>
        <p class="error-page__text">${message}</p>
        <p class="error-page__links">
          <a class="button button--cta" href="/">На главную</a>
        </p>
      </section>
    </div>`;
}

// start рисует шапку и подвал и запускает загрузку страницы. Любая ошибка
// (404 из API, неверный ?page=, сбой сети) превращается в страницу ошибки в #app.
export async function start(layout, load) {
  renderLayout(layout);
  try {
    await load();
  } catch (err) {
    if (!(err instanceof ApiError)) console.error(err);
    mount($('#app'), errorView(err instanceof ApiError ? err.status : 500));
  }
}
