// Главная: гостю — что это за сервис и вход; вошедшему — форма нового разбора и список прошлых.
import { ApiError, projects, reviews } from '../api.js';
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
    <section class="hero">
      <p class="eyebrow">Разбор правок контрагента</p>
      <h1 class="hero__title">Две редакции — один договор с правками</h1>
      <p class="hero__note">Загрузите вашу редакцию и ответ контрагента. «Правки» сведут их в одну версию: что вставлено,
      что удалено, что изменено без отметки, и что по каждой правке говорит ваш плейбук.</p>
      <p class="hero__actions">
        <a class="button button--cta" href="/login">Войти</a>
        <a class="button button--ghost" href="/signup">Регистрация</a>
      </p>
    </section>
    <ol class="steps">
      <li class="steps__item"><span class="steps__num">01</span><span class="steps__title">Загрузите две редакции</span>
        <span class="steps__text">Свою отправленную и ответ контрагента: .docx, .odt или PDF с текстом.</span></li>
      <li class="steps__item"><span class="steps__num">02</span><span class="steps__title">Получите единую версию</span>
        <span class="steps__text">Правки в тексте, правки без отметки выделены отдельно.</span></li>
      <li class="steps__item"><span class="steps__num">03</span><span class="steps__title">Решения на полях</span>
        <span class="steps__text">Плейбук решает, ИИ поясняет, сомнения — юристу. Тот же файл в Word.</span></li>
    </ol>`;
}

function formView(playbooks, memo, contracts, chosen) {
  const options = playbooks.map((p) => html`<option value="${p.key}" data-role="${p.role}"${p.key === memo.playbook ? ' selected' : ''}>${p.name}</option>`);
  return html`
    <header class="page-header">
      <h1 class="page-title">Новый разбор</h1>
      <p class="page-subtitle">Редакция контрагента обязательна. Ваша отправленная редакция нужна, чтобы найти правки без режима рецензирования; для PDF она обязательна: в PDF рецензирования нет. Word с примечаниями и ответ в Word — только для .docx.</p>
    </header>
    <p class="alert" role="alert" id="review-alert" hidden></p>
    <form class="form form--wide" id="review-form" novalidate>
      <div class="drops">
        <label class="drop" for="f-base">
          <span class="drop__icon" aria-hidden="true">⇪</span>
          <span class="drop__title">Наша редакция</span>
          <span class="drop__file" data-empty="Отправленная контрагенту, .docx или .odt — перетащите или выберите">Отправленная контрагенту, .docx или .odt — перетащите или выберите</span>
          <input id="f-base" name="base" type="file" accept=".docx,.odt,.pdf">
        </label>
        <label class="drop drop--main" for="f-theirs">
          <span class="drop__icon" aria-hidden="true">⇪</span>
          <span class="drop__title">Редакция контрагента</span>
          <span class="drop__file" data-empty="Его ответ, .docx, .odt или PDF — перетащите или выберите">Его ответ, .docx, .odt или PDF — перетащите или выберите</span>
          <input id="f-theirs" name="theirs" type="file" accept=".docx,.odt,.pdf" required>
        </label>
      </div>
      <div class="form__row">
        <div class="form__field">
          <label class="form__label" for="f-project">Договор</label>
          <select class="form__input" id="f-project" name="project_id">
            <option value="">Новый договор</option>
            ${contracts.map((c) => html`<option value="${c.id}" data-playbook="${c.playbook}" data-role="${c.our_role}"${c.id === chosen ? ' selected' : ''}>Следующий раунд: ${c.name} (раундов: ${c.rounds})</option>`)}
          </select>
        </div>
        <div class="form__field" id="f-project-name-field">
          <label class="form__label" for="f-project-name">Название нового договора</label>
          <input class="form__input" id="f-project-name" name="project_name" type="text" maxlength="255" placeholder="по умолчанию — имя файла контрагента">
        </div>
      </div>
      <div class="form__field">
        <label class="form__label" for="f-playbook">Плейбук</label>
        <select class="form__input" id="f-playbook" name="playbook">
          <option value="">Без плейбука — только найти и показать правки</option>
          ${options}
        </select>
      </div>
      <details class="more">
        <summary class="more__summary">Дополнительно: авторы правок, компания, сторона</summary>
      <div class="form__row">
        <div class="form__field">
          <label class="form__label" for="f-authors">Авторы ваших правок в Word</label>
          <input class="form__input" id="f-authors" name="our_authors" type="text" maxlength="500" value="${memo.our_authors || ''}" placeholder="через запятую, как они подписаны в Word: Иванов И.И., Петрова А.С.">
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
      </details>
      <p><button class="button button--cta" type="submit" id="review-submit">Свести и разобрать →</button></p>
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

const RECENT = 8; // сколько последних разборов показывать сразу

function projectsView(contracts) {
  if (!contracts.length) return emptyState('Договоров пока нет. Загрузите первый выше.');
  const cards = contracts.map((c) => html`
    <a class="card" href="/projects/${c.id}" data-name="${c.name.toLowerCase()}">
      <span class="card__title">${c.name}</span>
      <span class="card__meta">${c.playbook_name || 'без плейбука'}</span>
      <span class="card__foot">
        <span class="chip">раундов: ${c.rounds}</span>
        <span class="card__date">${fmtDate(c.last_at)}</span>
      </span>
    </a>`);
  return html`
    <input class="form__input search" id="project-search" type="search" placeholder="Найти договор…" aria-label="Найти договор">
    <div class="cards" id="project-cards">${cards}</div>
    <p class="form__hint" id="project-none" hidden>Ничего не найдено.</p>`;
}

function listView(items) {
  if (!items.length) return emptyState('Разборов пока нет. Загрузите первый договор выше.');
  const rows = items.map((r, i) => html`
    <tr${i >= RECENT ? html` class="is-extra" hidden` : ''}>
      <td>${fmtDate(r.created_at)}</td>
      <td><a href="/reviews/${r.id}">${r.theirs_name}</a></td>
      <td>${r.project_name ? html`<a href="/projects/${r.project_id}">${r.project_name}</a> · раунд ${r.round}` : '—'}</td>
      <td>${r.playbook_name || '—'}</td>
      ${COUNTS.map(([k]) => html`<td class="num">${(r.counts || {})[k] ?? 0}</td>`)}
    </tr>`);
  return html`
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Когда</th><th>Файл контрагента</th><th>Договор</th><th>Плейбук</th>${COUNTS.map(([, l]) => html`<th class="num">${l}</th>`)}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    ${items.length > RECENT ? html`<p><button class="button button--ghost button--small" type="button" id="show-all">Показать все (${items.length})</button></p>` : ''}`;
}

async function loggedInView() {
  const [playbooks, items, contracts] = await Promise.all([reviews.playbooks().catch(() => null), reviews.list(50, 0),
    projects.list().catch(() => [])]);
  const memo = memoLoad();
  const asked = Number(new URLSearchParams(location.search).get('project')) || 0; // ссылка «Следующий раунд»
  const chosen = (contracts || []).some((c) => c.id === asked) ? asked : 0;
  mount($('#home'), html`
    ${playbooks === null ? html`<p class="alert">Движок разбора не отвечает: список плейбуков не загружен. Разбор без плейбука всё равно можно запустить.</p>` : ''}
    ${formView(playbooks || [], memo, contracts || [], chosen)}
    <section class="section" aria-labelledby="projects-title">
      <div class="section-heading"><h2 class="section-heading__title" id="projects-title">Мои договоры</h2></div>
      ${projectsView(contracts || [])}
    </section>
    <section class="section" aria-labelledby="list-title">
      <div class="section-heading"><h2 class="section-heading__title" id="list-title">Последние разборы</h2></div>
      ${listView(items || [])}
    </section>`);
  wireForm();
  wireLists();
}

// Поиск по договорам и «показать все» в списке разборов.
function wireLists() {
  const search = $('#project-search');
  if (search) {
    search.addEventListener('input', () => {
      const q = search.value.trim().toLowerCase();
      let shown = 0;
      document.querySelectorAll('#project-cards .card').forEach((card) => {
        const hit = !q || card.dataset.name.includes(q);
        card.hidden = !hit;
        if (hit) shown++;
      });
      $('#project-none').hidden = shown > 0;
    });
  }
  const all = $('#show-all');
  if (all) {
    all.addEventListener('click', () => {
      document.querySelectorAll('.is-extra').forEach((row) => { row.hidden = false; });
      all.hidden = true;
    });
  }
}

// Зоны загрузки: показать имя выбранного файла и подсветить зону, когда над ней держат файл.
function wireDrops() {
  document.querySelectorAll('.drop').forEach((drop) => {
    const input = drop.querySelector('input');
    const label = drop.querySelector('.drop__file');
    const show = () => {
      const f = input.files[0];
      label.textContent = f ? f.name : label.dataset.empty;
      drop.classList.toggle('has-file', !!f);
    };
    input.addEventListener('change', show);
    input.addEventListener('dragenter', () => drop.classList.add('is-over'));
    ['dragleave', 'drop'].forEach((e) => input.addEventListener(e, () => drop.classList.remove('is-over')));
    show();
  });
}

// Выбран существующий договор: плейбук берём из прошлого раунда и не даём поменять (роль у договора одна),
// а поле названия нового договора прячем.
function wireProject() {
  const project = $('#f-project');
  const playbook = $('#f-playbook');
  const apply = () => {
    const opt = project.selectedOptions[0];
    const existing = !!project.value;
    $('#f-project-name-field').hidden = existing;
    if (existing && opt.dataset.playbook && [...playbook.options].some((o) => o.value === opt.dataset.playbook)) {
      playbook.value = opt.dataset.playbook;
    }
    playbook.disabled = existing && !!opt.dataset.playbook;
  };
  project.addEventListener('change', apply);
  apply();
}

function wireForm() {
  wireDrops();
  wireProject();
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
      show('Выберите файл редакции контрагента (.docx, .odt или PDF).');
      $('#f-theirs').focus();
      return;
    }
    if (/\.pdf$/i.test(theirs.name) && !$('#f-base').files[0]) {
      show('Для PDF загрузите и вашу отправленную редакцию: в PDF нет рецензирования, правки находятся сравнением с ней.');
      $('#f-base').focus();
      return;
    }
    const select = $('#f-playbook');
    const role = select.selectedOptions[0] ? select.selectedOptions[0].dataset.role || '' : '';
    const confirm = $('#f-confirm').checked;
    memoSave({ our_authors: $('#f-authors').value, company: $('#f-company').value, playbook: $('#f-project').value ? memoLoad().playbook : select.value, confirm });

    const fd = new FormData();
    fd.append('theirs', theirs);
    const base = $('#f-base').files[0];
    if (base) fd.append('base', base);
    fd.append('playbook', select.value);
    if ($('#f-project').value) fd.append('project_id', $('#f-project').value);
    else fd.append('project_name', $('#f-project-name').value);
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
        submit.textContent = `Подтвердить роль «${err.data.role}» и разобрать →`;
      } else if (status === 400) {
        // текст ошибки проверки (неверный файл, роль не совпала с прошлыми раундами) — для юриста, без служебного хвоста
        show(`Не удалось разобрать: ${(err.detail || '').replace(/: invalid argument$/, '') || err.message}`);
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
