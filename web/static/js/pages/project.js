// Страница договора: все раунды переговоров и что в каждом нового по сравнению с прошлыми.
// Только сведения для юриста: решения по правкам принимает плейбук и юрист.
import { ApiError, counterparties, projects } from '../api.js';
import { $, currentUser, errorView, html, mount, pathID, renderLayout, setTitle } from '../ui.js';
import { fmtDate, memoLoad, memoSave, wireDrops, wireReviewSubmit } from '../upload.js';

renderLayout({ nav: 'home', navDetail: true });

const COLUMNS = [
  ['total', 'Правок'],
  ['new', 'Новых'],
  ['repeat', 'Повторных'],
  ['returned', 'Вернулись к пункту'],
  ['closed', 'Снято контрагентом'],
];

function roundsTable(rounds) {
  return html`
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Раунд</th><th>Когда</th><th>Файл контрагента</th>${COLUMNS.map(([, l]) => html`<th class="num">${l}</th>`)}</tr></thead>
        <tbody>
          ${rounds.map((r) => html`<tr>
            <td><a href="/reviews/${r.review_id}">Раунд ${r.round}</a></td>
            <td>${fmtDate(r.created_at)}</td>
            <td>${r.theirs_name}</td>
            ${COLUMNS.map(([k]) => html`<td class="num${k === 'returned' && r[k] ? ' num--hot' : ''}">${r.round === 1 && k !== 'total' && k !== 'new' ? '—' : r[k]}</td>`)}
          </tr>`)}
        </tbody>
      </table>
    </div>
    <p class="form__hint">«Повторных» — та же правка слово в слово уже была раньше. «Вернулись к пункту» — тот же пункт и тема, но другое значение.
    «Снято» — правки прошлого раунда, которых в этом нет: контрагент от них отказался или принял вашу встречную редакцию.</p>`;
}

// Новый раунд: присланная контрагентом версия (и, по желанию, наша отправленная, чтобы найти правки без отметки).
// Плейбук тот же, что в прошлых раундах: роль у договора одна.
function roundForm(p, memo) {
  return html`
    <section class="section" id="new-round" aria-labelledby="new-round-title">
      <div class="section-heading"><h2 class="section-heading__title" id="new-round-title">Новый раунд</h2></div>
      <p class="alert" role="alert" id="review-alert" hidden></p>
      <form class="form form--wide" id="review-form" novalidate>
        <div class="drops">
          <label class="drop drop--main" for="f-theirs">
            <span class="drop__icon" aria-hidden="true">⇪</span>
            <span class="drop__title">Версия контрагента</span>
            <span class="drop__file" data-empty="Его ответ с правками: .docx, .odt или PDF">Его ответ с правками: .docx, .odt или PDF</span>
            <input id="f-theirs" name="theirs" type="file" accept=".docx,.odt,.pdf" required>
          </label>
          <label class="drop" for="f-base">
            <span class="drop__icon" aria-hidden="true">⇪</span>
            <span class="drop__title">Наша отправленная версия</span>
            <span class="drop__file" data-empty="По желанию (для PDF обязательно): так найдутся правки без отметки">По желанию (для PDF обязательно): так найдутся правки без отметки</span>
            <input id="f-base" name="base" type="file" accept=".docx,.odt,.pdf">
          </label>
        </div>
        <details class="more">
          <summary class="more__summary">Дополнительно: ваша компания, авторы правок, сторона</summary>
          <div class="form__row">
            <div class="form__field">
              <label class="form__label" for="f-company">ИНН или наименование вашей компании</label>
              <input class="form__input" id="f-company" type="text" maxlength="500" value="${memo.company || ''}">
            </div>
            <div class="form__field">
              <label class="form__label" for="f-authors">Авторы ваших правок в Word</label>
              <input class="form__input" id="f-authors" type="text" maxlength="500" value="${memo.our_authors || ''}" placeholder="через запятую, как они подписаны в Word">
            </div>
          </div>
          ${p.our_role ? html`<label class="check">
            <input type="checkbox" id="f-confirm"${memo.confirm ? ' checked' : ''}>
            <span>Подтверждаю роль «${p.our_role}» вручную (если сторона в договоре названа иначе, чем в плейбуке)</span>
          </label>` : ''}
        </details>
        <p><button class="button button--cta" type="submit" id="review-submit">Добавить раунд и разобрать →</button></p>
        <p class="form__hint" id="review-progress" hidden role="status">Разбираю договор… Это может занять до нескольких минут.</p>
      </form>
    </section>`;
}

function wireRoundForm(p) {
  const alertBox = $('#review-alert');
  const show = (msg) => {
    alertBox.textContent = msg;
    alertBox.hidden = !msg;
  };
  wireDrops();
  wireReviewSubmit({
    form: $('#review-form'), submit: $('#review-submit'), progress: $('#review-progress'), show,
    collect() {
      const theirs = $('#f-theirs').files[0];
      const base = $('#f-base').files[0];
      if (!theirs) {
        show('Выберите файл версии контрагента (.docx, .odt или PDF).');
        return null;
      }
      if (/\.pdf$/i.test(theirs.name) && !base) {
        show('Для PDF загрузите и вашу отправленную версию: в PDF нет рецензирования, правки находятся сравнением с ней.');
        $('#f-base').focus();
        return null;
      }
      const confirmBox = $('#f-confirm');
      const confirm = !!(confirmBox && confirmBox.checked);
      memoSave({ our_authors: $('#f-authors').value, company: $('#f-company').value, confirm });
      const fd = new FormData();
      fd.append('theirs', theirs);
      if (base) fd.append('base', base);
      fd.append('project_id', String(p.id));
      fd.append('playbook', p.playbook || '');
      fd.append('our_authors', $('#f-authors').value);
      fd.append('company', $('#f-company').value);
      return { fd, role: p.our_role || '', confirm };
    },
  });
}

// Перенести договор к другому контрагенту (например, из «Без контрагента»). Папка на диске остаётся прежней.
function moveForm(p, list) {
  const others = list.filter((c) => c.id !== p.counterparty_id);
  if (!others.length) return '';
  return html`
    <details class="more">
      <summary class="more__summary">Перенести договор к другому контрагенту</summary>
      <form class="form" id="move-form">
        <div class="form__field">
          <label class="form__label" for="move-to">Контрагент</label>
          <select class="form__input" id="move-to">${others.map((c) => html`<option value="${c.id}">${c.name}</option>`)}</select>
        </div>
        <p><button class="button button--small" type="submit" id="move-save">Перенести</button>
        <span class="form__hint" id="move-status" role="status"></span></p>
        ${p.has_folder ? html`<p class="form__hint">Файлы в папке на диске останутся на прежнем месте.</p>` : ''}
      </form>
    </details>`;
}

function wireMoveForm(p) {
  const form = $('#move-form');
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('#move-save');
    button.disabled = true;
    $('#move-status').textContent = 'Переношу…';
    try {
      await projects.move(p.id, Number($('#move-to').value));
      location.reload();
    } catch {
      $('#move-status').textContent = 'Не удалось перенести. Попробуйте ещё раз.';
      button.disabled = false;
    }
  });
}

async function load() {
  const user = await currentUser();
  if (!user) {
    location.replace('/login?next=' + encodeURIComponent(location.pathname));
    return;
  }
  const [v, cps] = await Promise.all([projects.get(pathID()), counterparties.list().catch(() => [])]);
  const p = v.project;
  setTitle(p.name);
  const last = v.rounds[v.rounds.length - 1];
  mount($('#project'), html`
    <header class="page-header">
      <p class="eyebrow"><a href="/">Контрагенты</a> › <a href="/counterparties/${p.counterparty_id}">${p.counterparty_name}</a></p>
      <h1 class="page-title">${p.name}</h1>
      <p class="page-subtitle">Раундов: ${p.rounds}${p.playbook_name ? html` · Плейбук: ${p.playbook_name}` : ''}${p.our_role ? html` · мы — ${p.our_role}` : ''}</p>
      <p class="actions">
        <a class="button button--cta" href="#new-round">Добавить раунд</a>
        ${last ? html`<a class="button button--ghost" href="/reviews/${last.review_id}">Последний раунд</a>` : ''}
        <a class="button button--ghost" href="/counterparties/${p.counterparty_id}">К контрагенту</a>
      </p>
    </header>
    ${v.rounds.length ? roundsTable(v.rounds) : html`<p class="empty-state">Раундов нет.</p>`}
    ${roundForm(p, memoLoad())}
    ${moveForm(p, cps)}`);
  wireRoundForm(p);
  wireMoveForm(p);
}

load().catch((err) => {
  if (!(err instanceof ApiError)) console.error(err);
  mount($('#project'), errorView(err instanceof ApiError ? err.status : 500));
});
