// Страница договора: все раунды переговоров и что в каждом нового по сравнению с прошлыми.
// Только сведения для юриста: решения по правкам принимает плейбук и юрист.
import { ApiError, projects } from '../api.js';
import { $, currentUser, errorView, html, mount, pathID, renderLayout, setTitle } from '../ui.js';

renderLayout({ nav: 'home', navDetail: true });

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
  } catch {
    return iso;
  }
}

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

async function load() {
  const user = await currentUser();
  if (!user) {
    location.replace('/login?next=' + encodeURIComponent(location.pathname));
    return;
  }
  const v = await projects.get(pathID());
  const p = v.project;
  setTitle(p.name);
  const last = v.rounds[v.rounds.length - 1];
  mount($('#project'), html`
    <header class="page-header">
      <p class="eyebrow">Договор</p>
      <h1 class="page-title">${p.name}</h1>
      <p class="page-subtitle">Раундов: ${p.rounds}${p.playbook_name ? html` · Плейбук: ${p.playbook_name}` : ''}${p.our_role ? html` · мы — ${p.our_role}` : ''}</p>
      <p class="actions">
        ${last ? html`<a class="button button--cta" href="/?project=${p.id}">Следующий раунд</a>` : ''}
        <a class="button button--ghost" href="/">Все разборы</a>
      </p>
    </header>
    ${v.rounds.length ? roundsTable(v.rounds) : html`<p class="empty-state">Раундов нет.</p>`}`);
}

load().catch((err) => {
  if (!(err instanceof ApiError)) console.error(err);
  mount($('#project'), errorView(err instanceof ApiError ? err.status : 500));
});
