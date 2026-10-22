// Главная: гостю — что это за сервис и вход; вошедшему — форма нового разбора и список прошлых.
import { ApiError, reviews } from '../api.js';
import { $, currentUser, emptyState, html, mount, renderLayout, setTitle } from '../ui.js';

renderLayout({ nav: 'home' });
setTitle('');

const COUNTS = [
  ['всего', 'Правок'],
  ['нужно решение юриста', 'Решает юрист'],
  ['красные линии', 'Красные линии'],
];

// Поля, которые удобно не вводить каждый раз. Хранятся только в этом браузере; сбой хранилища не мешает работе.
const MEMO = 'pravki.form';
function memoLoad() {
  try {
    return JSON.parse(localStorage.getItem(MEMO) || '{}');
  } catch {
    return {};
  }
}
function memoSave(v) {
  try {
    localStorage.setItem(MEMO, JSON.stringify(v));
  } catch {
    /* приватный режим и т.п. */
  }
}

function guestView() {
  return html`
    <section class="hero hero--compact">
      <h1 class="hero__title"><span class="hero__line">Разбор правок контрагента в договоре.</span></h1>
      <p class="hero__note">Загрузите версию контрагента — получите отчёт: какие правки внесены, какие из них «тихие»,
      и что по ним говорит ваш плейбук.</p>
      <p class="hero__actions">
        <a class="button button--cta" href="/login">Войти</a>
        <a class="button button--ghost" href="/signup">Регистрация</a>
      </p>
    </section>`;
}

function formView(playbooks, memo) {
  const options = playbooks.map((p) => html`<option value="${p.key}" data-role="${p.role}"${p.key === memo.playbook ? ' selected' : ''}>${p.name}</option>`);
  return html`
    <header class="page-header">
      <h1 class="page-title">Новый разбор</h1>
      <p class="page-subtitle">Версия контрагента обязательна. Ваша отправленная версия нужна, чтобы найти правки без режима рецензирования.</p>
    </header>
    <p class="alert" role="alert" id="review-alert" hidden></p>
    <form class="form form--wide" id="review-form" novalidate>
      <div class="form__row">
        <div class="form__field">
          <label class="form__label" for="f-theirs">Версия контрагента (.docx)</label>
          <input class="form__input" id="f-theirs" name="theirs" type="file" accept=".docx" required>
        </div>
        <div class="form__field">
          <label class="form__label" for="f-base">Ваша отправленная версия (.docx)</label>
          <input class="form__input" id="f-base" name="base" type="file" accept=".docx">
        </div>
      </div>
      <div class="form__field">
        <label class="form__label" for="f-playbook">Плейбук</label>
        <select class="form__input" id="f-playbook" name="playbook">
          <option value="">Без плейбука — только найти и показать правки</option>
          ${options}
        </select>
      </div>
      <div class="form__row">
        <div class="form__field">
          <label class="form__label" for="f-authors">Авторы ваших правок в Word</label>
          <input class="form__input" id="f-authors" name="our_authors" type="text" maxlength="500" value="${memo.our_authors || ''}" placeholder="через запятую, например: kandu, Zuev Pavel">
        </div>
        <div class="form__field">
          <label class="form__label" for="f-company">ИНН или наименование вашей компании</label>
          <input class="form__input" id="f-company" name="company" type="text" maxlength="500" value="${memo.company || ''}" placeholder="по ним программа найдёт вашу сторону">
        </div>
      </div>
      <label class="check">
        <input type="checkbox" id="f-confirm"${memo.confirm ? ' checked' : ''}>
        <span>Ваша сторона в договоре называется иначе, чем в плейбуке (например, «Участник» вместо «Заказчика») — подтверждаю роль плейбука вручную</span>
      </label>
      <button class="button button--cta" type="submit" id="review-submit">Разобрать</button>
      <p class="form__hint" id="review-progress" hidden role="status">Разбираю договор… Это может занять до нескольких минут.</p>
    </form>`;
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
  } catch {
    return iso;
  }
}

function listView(items) {
  if (!items.length) return emptyState('Разборов пока нет. Загрузите первый договор выше.');
  const rows = items.map((r) => html`
    <tr>
      <td>${fmtDate(r.created_at)}</td>
      <td><a href="/reviews/${r.id}">${r.theirs_name}</a></td>
      <td>${r.playbook_name || '—'}</td>
      ${COUNTS.map(([k]) => html`<td class="num">${(r.counts || {})[k] ?? 0}</td>`)}
    </tr>`);
  return html`
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Когда</th><th>Файл контрагента</th><th>Плейбук</th>${COUNTS.map(([, l]) => html`<th class="num">${l}</th>`)}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function loggedInView() {
  const [playbooks, items] = await Promise.all([reviews.playbooks().catch(() => null), reviews.list(50, 0)]);
  const memo = memoLoad();
  mount($('#home'), html`
    ${playbooks === null ? html`<p class="alert">Движок разбора не отвечает: список плейбуков не загружен. Разбор без плейбука всё равно можно запустить.</p>` : ''}
    ${formView(playbooks || [], memo)}
    <section class="section" aria-labelledby="list-title">
      <div class="section-heading"><h2 class="section-heading__title" id="list-title">Мои разборы</h2></div>
      ${listView(items || [])}
    </section>`);
  wireForm();
}

function wireForm() {
  const form = $('#review-form');
  const alertBox = $('#review-alert');
  const submit = $('#review-submit');
  const progress = $('#review-progress');
  let confirmRole = ''; // роль, которую юрист подтвердил после ответа 422

  const show = (msg) => {
    alertBox.textContent = msg;
    alertBox.hidden = !msg;
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    show('');
    const theirs = $('#f-theirs').files[0];
    if (!theirs) {
      show('Выберите файл версии контрагента (.docx).');
      $('#f-theirs').focus();
      return;
    }
    const select = $('#f-playbook');
    const role = select.selectedOptions[0] ? select.selectedOptions[0].dataset.role || '' : '';
    const confirm = $('#f-confirm').checked;
    memoSave({ our_authors: $('#f-authors').value, company: $('#f-company').value, playbook: select.value, confirm });

    const fd = new FormData();
    fd.append('theirs', theirs);
    const base = $('#f-base').files[0];
    if (base) fd.append('base', base);
    fd.append('playbook', select.value);
    fd.append('our_authors', $('#f-authors').value);
    fd.append('company', $('#f-company').value);
    if (confirmRole || (confirm && role)) fd.append('confirm_role', confirmRole || role);

    submit.disabled = true;
    progress.hidden = false;
    try {
      const rev = await reviews.create(fd);
      location.href = '/reviews/' + rev.id;
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 422 && err.data && err.data.role) {
        confirmRole = err.data.role;
        show(`Сторона договора не подтверждена: ${err.message} Если вы действительно «${err.data.role}», нажмите «Разобрать» ещё раз — роль будет подтверждена вручную.`);
        submit.textContent = `Подтвердить роль «${err.data.role}» и разобрать`;
      } else if (status === 400) {
        show(`Не удалось разобрать: ${err.message}`);
      } else if (status === 502) {
        show('Движок разбора не отвечает. Проверьте, что контейнер engine запущен, и попробуйте ещё раз.');
      } else if (status === 401) {
        location.href = '/login?next=/';
      } else {
        show('Не удалось выполнить разбор. Попробуйте ещё раз чуть позже.');
      }
      submit.disabled = false;
      progress.hidden = true;
    }
  });
}

currentUser().then(async (user) => {
  if (!user) {
    mount($('#home'), guestView());
    return;
  }
  try {
    await loggedInView();
  } catch (err) {
    if (!(err instanceof ApiError)) console.error(err);
    mount($('#home'), html`<p class="alert">Не удалось загрузить разборы. Обновите страницу чуть позже.</p>`);
  }
});
