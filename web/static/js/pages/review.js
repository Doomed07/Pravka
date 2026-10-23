// Страница разбора: сводка, предупреждения, отчёт движка во встроенном окне, Excel и удаление.
import { ApiError, reviews } from '../api.js';
import { $, currentUser, errorView, html, mount, pathID, renderLayout, setTitle } from '../ui.js';

renderLayout({ nav: 'home', navDetail: true });

const TILES = [
  ['всего', 'Правок всего'],
  ['нужно решение юриста', 'Решает юрист'],
  ['красные линии', 'Красные линии'],
  ['тихие правки', 'Тихие правки'],
  ['комментарии', 'Комментарии'],
];

function view(r) {
  const c = r.counts || {};
  const warnings = r.warnings || [];
  return html`
    <header class="page-header">
      <h1 class="page-title">${r.theirs_name}</h1>
      <p class="page-subtitle">
        Ваша версия: ${r.base_name || 'не загружена'} · Плейбук: ${r.playbook_name || 'без плейбука'}${r.side ? html` · ${r.side}` : ''}
      </p>
    </header>
    <dl class="tiles">
      ${TILES.map(([k, label]) => html`<div class="tiles__item"><dt>${label}</dt><dd>${c[k] ?? 0}</dd></div>`)}
    </dl>
    ${warnings.length ? html`<div class="alert"><strong>Обратите внимание</strong><ul class="alert__list">${warnings.map((w) => html`<li>${w}</li>`)}</ul></div>` : ''}
    <p class="actions">
      <a class="button button--cta" href="/api/v1/reviews/${r.id}/report" target="_blank" rel="noopener">Открыть отчёт в новой вкладке</a>
      <a class="button button--ghost" href="/api/v1/reviews/${r.id}/xlsx">Скачать Excel</a>
      <a class="button button--ghost" href="/">Новый разбор</a>
      <button class="button button--danger" type="button" id="delete">Удалить разбор</button>
    </p>
    <iframe class="report-frame" src="/api/v1/reviews/${r.id}/report" title="Отчёт" sandbox=""></iframe>`;
}

async function load() {
  const user = await currentUser();
  if (!user) {
    location.replace('/login?next=' + encodeURIComponent(location.pathname));
    return;
  }
  const id = pathID();
  const r = await reviews.get(id);
  setTitle(r.theirs_name);
  mount($('#review'), view(r));

  // удаление в два нажатия, без всплывающих окон браузера
  const del = $('#delete');
  let armed = false;
  del.addEventListener('click', async () => {
    if (!armed) {
      armed = true;
      del.textContent = 'Точно удалить? Нажмите ещё раз';
      return;
    }
    del.disabled = true;
    try {
      await reviews.remove(id);
      location.href = '/';
    } catch {
      del.disabled = false;
      del.textContent = 'Не удалось удалить. Ещё раз?';
    }
  });
}

load().catch((err) => {
  if (!(err instanceof ApiError)) console.error(err);
  mount($('#review'), errorView(err instanceof ApiError ? err.status : 500));
});
