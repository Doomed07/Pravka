// Страница контрагента: его договоры. Договор открывает раунды.
import { ApiError, counterparties, projects } from '../api.js';
import { $, currentUser, emptyState, errorView, html, mount, pathID, renderLayout, setTitle } from '../ui.js';
import { fmtDate } from '../upload.js';

renderLayout({ nav: 'home', navDetail: true });

function contractCards(list) {
  if (!list.length) return emptyState('У контрагента пока нет договоров.');
  return html`<div class="cards" id="contracts">${list.map((p) => html`
    <div class="card-box" data-project="${p.id}">
      <a class="card" href="/projects/${p.id}">
        <span class="card__title">${p.name}</span>
        <span class="card__meta">${p.playbook_name || 'без плейбука'}${p.our_role ? ` · мы — ${p.our_role}` : ''}</span>
        <span class="card__foot">
          <span class="chip">раундов: ${p.rounds}</span>
          <span class="card__date">${fmtDate(p.last_at)}</span>
        </span>
      </a>
      <button class="button button--ghost button--small card-box__del" type="button">Удалить</button>
    </div>`)}</div>`;
}

// Удаление договора в два нажатия, без всплывающих окон браузера: раунды уходят с сайта, файлы на диске остаются
function wireDeletes() {
  document.querySelectorAll('.card-box').forEach((box) => {
    const button = box.querySelector('.card-box__del');
    let armed = false;
    let timer;
    const reset = () => {
      armed = false;
      button.textContent = 'Удалить';
      button.classList.remove('button--danger');
    };
    button.addEventListener('click', async () => {
      if (!armed) {
        armed = true;
        button.textContent = 'Точно удалить? Нажмите ещё раз';
        button.classList.add('button--danger');
        clearTimeout(timer);
        timer = setTimeout(reset, 5000); // передумали — кнопка возвращается сама
        return;
      }
      button.disabled = true;
      button.textContent = 'Удаляю…';
      try {
        await projects.remove(box.dataset.project);
        location.reload();
      } catch {
        button.disabled = false;
        reset();
        button.textContent = 'Не удалось. Ещё раз?';
      }
    });
  });
}

function renameForm(c) {
  return html`
    <details class="more">
      <summary class="more__summary">Изменить название или ИНН</summary>
      <form class="form" id="rename-form" novalidate>
        <div class="form__row">
          <div class="form__field">
            <label class="form__label" for="cp-name">Название</label>
            <input class="form__input" id="cp-name" type="text" maxlength="255" value="${c.name}">
          </div>
          <div class="form__field">
            <label class="form__label" for="cp-inn">ИНН</label>
            <input class="form__input" id="cp-inn" type="text" inputmode="numeric" maxlength="12" value="${c.inn}">
          </div>
        </div>
        <p><button class="button button--small" type="submit" id="rename-save">Сохранить</button>
        <span class="form__hint" id="rename-status" role="status"></span></p>
        <p class="form__hint">Папка на диске не переименовывается: файлы остаются на месте.</p>
      </form>
    </details>`;
}

async function load() {
  const user = await currentUser();
  if (!user) {
    location.replace('/login?next=' + encodeURIComponent(location.pathname));
    return;
  }
  const id = pathID();
  const v = await counterparties.get(id);
  const c = v.counterparty;
  setTitle(c.name);
  mount($('#counterparty'), html`
    <header class="page-header">
      <p class="eyebrow"><a href="/">Контрагенты</a></p>
      <h1 class="page-title">${c.name}</h1>
      <p class="page-subtitle">${c.inn ? `ИНН ${c.inn} · ` : ''}договоров: ${c.contracts} · раундов: ${c.rounds}${c.has_folder ? ' · файлы лежат в папке на диске' : ''}</p>
      <p class="actions"><a class="button button--cta" href="/?counterparty=${c.id}">Новый договор</a></p>
    </header>
    ${renameForm(c)}
    <section class="section" aria-labelledby="contracts-title">
      <div class="section-heading"><h2 class="section-heading__title" id="contracts-title">Договоры</h2></div>
      ${contractCards(v.projects)}
    </section>`);

  wireDeletes();

  const form = $('#rename-form');
  const status = $('#rename-status');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('#rename-save');
    button.disabled = true;
    status.textContent = 'Сохраняю…';
    try {
      await counterparties.update(id, $('#cp-name').value, $('#cp-inn').value.trim());
      location.reload();
    } catch (err) {
      status.textContent = err instanceof ApiError && err.status === 409 ? 'Контрагент с таким названием уже есть.'
        : err instanceof ApiError && err.status === 400 ? 'Проверьте название и ИНН (10 или 12 цифр).' : 'Не сохранено, попробуйте ещё раз.';
      button.disabled = false;
    }
  });
}

load().catch((err) => {
  if (!(err instanceof ApiError)) console.error(err);
  mount($('#counterparty'), errorView(err instanceof ApiError ? err.status : 500));
});
