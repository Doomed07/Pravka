// Главная: гостю — что это за сервис и вход; вошедшему — загрузка первой версии договора, контрагенты и последние разборы.
import { ApiError, contracts, counterparties, reviews } from '../api.js';
import { $, currentUser, emptyState, html, mount, renderLayout, setTitle } from '../ui.js';
import { fmtDate, memoLoad, memoSave, wireDrops, wireReviewSubmit } from '../upload.js';

renderLayout({ nav: 'home' });
setTitle('');

const COUNTS = [
  ['всего', 'Правок'],
  ['нужно решение юриста', 'Решает юрист'],
  ['красные линии', 'Красные линии'],
];

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

// Первая версия договора: так, как её прислал контрагент, без наших правок. Файл выбран — программа находит контрагента
// по преамбуле, юрист подтверждает или правит и запускает разбор.
function uploadView(playbooks, memo) {
  const options = playbooks.map((p) => html`<option value="${p.key}" data-role="${p.role}"${p.key === memo.playbook ? ' selected' : ''}>${p.name}</option>`);
  return html`
    <header class="page-header">
      <h1 class="page-title">Новый договор</h1>
      <p class="page-subtitle">Загрузите первую версию — так, как её прислал контрагент, без ваших правок. Программа найдёт контрагента, создаст договор
      и папку для него. Следующие версии добавляются на странице договора.</p>
    </header>
    <p class="alert" role="alert" id="review-alert" hidden></p>
    <form class="form form--wide" id="review-form" novalidate>
      <label class="drop drop--main drop--big" for="f-theirs">
        <span class="drop__icon" aria-hidden="true">⇪</span>
        <span class="drop__title">Первая версия договора</span>
        <span class="drop__file" data-empty="Перетащите файл сюда или выберите: .docx, .odt или PDF">Перетащите файл сюда или выберите: .docx, .odt или PDF</span>
        <input id="f-theirs" name="theirs" type="file" accept=".docx,.odt,.pdf" required>
      </label>
      <p class="form__hint" id="detect-status" role="status" hidden></p>
      <p class="chips" id="detect-parties" hidden></p>
      <section class="confirm" id="confirm" aria-labelledby="confirm-title" hidden>
        <h2 class="confirm__title" id="confirm-title">Проверьте данные</h2>
        <div class="form__row">
          <div class="form__field">
            <label class="form__label" for="f-cp">Контрагент</label>
            <select class="form__input" id="f-cp" name="counterparty_id"><option value="">Новый контрагент</option></select>
          </div>
          <div class="form__field" id="f-cp-new">
            <label class="form__label" for="f-cp-name">Название контрагента</label>
            <input class="form__input" id="f-cp-name" name="counterparty_name" type="text" maxlength="255" placeholder="например, ООО «Ромашка»">
          </div>
          <div class="form__field" id="f-cp-inn-field">
            <label class="form__label" for="f-cp-inn">ИНН контрагента</label>
            <input class="form__input" id="f-cp-inn" name="counterparty_inn" type="text" inputmode="numeric" maxlength="12" placeholder="10 или 12 цифр, если есть">
          </div>
        </div>
        <div class="form__row">
          <div class="form__field">
            <label class="form__label" for="f-project-name">Название договора</label>
            <input class="form__input" id="f-project-name" name="project_name" type="text" maxlength="255" placeholder="по умолчанию — имя файла">
          </div>
          <div class="form__field">
            <label class="form__label" for="f-playbook">Плейбук</label>
            <select class="form__input" id="f-playbook" name="playbook">
              <option value="">Без плейбука — только найти и показать правки</option>
              ${options}
            </select>
          </div>
        </div>
        <details class="more">
          <summary class="more__summary">Дополнительно: ваша компания, авторы правок, сторона</summary>
          <div class="form__row">
            <div class="form__field">
              <label class="form__label" for="f-company">ИНН или наименование вашей компании</label>
              <input class="form__input" id="f-company" name="company" type="text" maxlength="500" value="${memo.company || ''}" placeholder="ИНН и/или название, например: 7701234567, ООО «Ромашка»">
            </div>
            <div class="form__field">
              <label class="form__label" for="f-authors">Авторы ваших правок в Word</label>
              <input class="form__input" id="f-authors" name="our_authors" type="text" maxlength="500" value="${memo.our_authors || ''}" placeholder="через запятую, как они подписаны в Word">
            </div>
          </div>
          <label class="check">
            <input type="checkbox" id="f-confirm"${memo.confirm ? ' checked' : ''}>
            <span>Ваша сторона в договоре называется иначе, чем в плейбуке (например, «Участник» вместо «Заказчика») — подтверждаю роль плейбука вручную</span>
          </label>
        </details>
        <p><button class="button button--cta" type="submit" id="review-submit">Создать договор и разобрать →</button></p>
        <p class="form__hint" id="review-progress" hidden role="status">Разбираю договор… Это может занять до нескольких минут.</p>
      </section>
    </form>`;
}

function counterpartiesView(list) {
  if (!list.length) return emptyState('Контрагентов пока нет. Загрузите первый договор выше.');
  const cards = list.map((c) => html`
    <a class="card" href="/counterparties/${c.id}" data-name="${c.name.toLowerCase()}">
      <span class="card__title">${c.name}</span>
      <span class="card__meta">${c.inn ? `ИНН ${c.inn}` : 'ИНН не указан'}</span>
      <span class="card__foot">
        <span class="chip">договоров: ${c.contracts}</span>
        <span class="card__date">${fmtDate(c.last_at)}</span>
      </span>
    </a>`);
  return html`
    <input class="form__input search" id="cp-search" type="search" placeholder="Найти контрагента…" aria-label="Найти контрагента">
    <div class="cards" id="cp-cards">${cards}</div>
    <p class="form__hint" id="cp-none" hidden>Ничего не найдено.</p>`;
}

const RECENT = 8; // сколько последних разборов показывать сразу

function listView(items) {
  if (!items.length) return emptyState('Разборов пока нет. Загрузите первый договор выше.');
  const rows = items.map((r, i) => html`
    <tr${i >= RECENT ? html` class="is-extra" hidden` : ''}>
      <td>${fmtDate(r.created_at)}</td>
      <td><a href="/reviews/${r.id}">${r.theirs_name}</a></td>
      <td>${r.counterparty_name ? html`<a href="/counterparties/${r.counterparty_id}">${r.counterparty_name}</a>` : '—'}</td>
      <td>${r.project_name ? html`<a href="/projects/${r.project_id}">${r.project_name}</a> · раунд ${r.round}` : '—'}</td>
      ${COUNTS.map(([k]) => html`<td class="num">${(r.counts || {})[k] ?? 0}</td>`)}
    </tr>`);
  return html`
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Когда</th><th>Файл контрагента</th><th>Контрагент</th><th>Договор</th>${COUNTS.map(([, l]) => html`<th class="num">${l}</th>`)}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    ${items.length > RECENT ? html`<p><button class="button button--ghost button--small" type="button" id="show-all">Показать все (${items.length})</button></p>` : ''}`;
}

async function loggedInView() {
  // старая ссылка «Следующий раунд» вела на главную: теперь раунды добавляются на странице договора
  const asked = Number(new URLSearchParams(location.search).get('project')) || 0;
  if (asked) {
    location.replace('/projects/' + asked);
    return;
  }
  const [playbooks, items, cps] = await Promise.all([reviews.playbooks().catch(() => null), reviews.list(50, 0),
    counterparties.list().catch(() => [])]);
  const memo = memoLoad();
  mount($('#home'), html`
    ${playbooks === null ? html`<p class="alert">Движок разбора не отвечает: список плейбуков не загружен. Разбор без плейбука всё равно можно запустить.</p>` : ''}
    ${uploadView(playbooks || [], memo)}
    <section class="section" aria-labelledby="cp-title">
      <div class="section-heading"><h2 class="section-heading__title" id="cp-title">Контрагенты</h2></div>
      ${counterpartiesView(cps || [])}
    </section>
    <section class="section" aria-labelledby="list-title">
      <div class="section-heading"><h2 class="section-heading__title" id="list-title">Последние разборы</h2></div>
      ${listView(items || [])}
    </section>`);
  wireForm(cps || []);
  wireLists();
}

// Поиск по контрагентам и «показать все» в списке разборов.
function wireLists() {
  const search = $('#cp-search');
  if (search) {
    search.addEventListener('input', () => {
      const q = search.value.trim().toLowerCase();
      let shown = 0;
      document.querySelectorAll('#cp-cards .card').forEach((card) => {
        const hit = !q || card.dataset.name.includes(q);
        card.hidden = !hit;
        if (hit) shown++;
      });
      $('#cp-none').hidden = shown > 0;
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

const stem = (name) => name.replace(/\.(docx|odt|pdf)$/i, '');

function wireForm(cps) {
  const form = $('#review-form');
  const alertBox = $('#review-alert');
  const confirmBox = $('#confirm');
  const status = $('#detect-status');
  const cpSelect = $('#f-cp');
  const preset = Number(new URLSearchParams(location.search).get('counterparty')) || 0; // «Новый договор» со страницы контрагента
  cps.forEach((c) => cpSelect.append(new Option(c.name, String(c.id))));

  const show = (msg) => {
    alertBox.textContent = msg;
    alertBox.hidden = !msg;
  };
  const syncCounterparty = () => {
    const existing = !!cpSelect.value;
    $('#f-cp-new').hidden = existing;
    $('#f-cp-inn-field').hidden = existing;
  };
  cpSelect.addEventListener('change', syncCounterparty);

  // найденное по договору: контрагент, наша компания, название договора и плейбук. Пользователь может всё поправить.
  const partyLine = (p) => [p.inn, p.name].filter(Boolean).join(', ');
  const setCounterparty = (cp) => {
    const same = cps.find((c) => c.name.toLowerCase() === cp.name.toLowerCase());
    cpSelect.value = same ? String(same.id) : '';
    $('#f-cp-name').value = same ? '' : cp.name;
    $('#f-cp-inn').value = same ? '' : cp.inn;
    syncCounterparty();
  };
  const fill = (found) => {
    const chips = $('#detect-parties');
    chips.hidden = true;
    chips.textContent = '';
    cpSelect.value = preset && cps.some((c) => c.id === preset) ? String(preset) : '';
    $('#f-cp-name').value = '';
    $('#f-cp-inn').value = '';
    const cp = found && found.counterparty;
    if (found && found.title && !$('#f-project-name').dataset.touched) $('#f-project-name').value = found.title;
    if (found && found.playbook && [...$('#f-playbook').options].some((o) => o.value === found.playbook)) {
      $('#f-playbook').value = found.playbook;
    }
    if (found && found.ours && !$('#f-company').value.trim()) $('#f-company').value = partyLine(found.ours);
    const how = found && found.source === 'model' ? ' (стороны нашла локальная модель, названия проверены по тексту договора)' : '';
    if (cp) {
      setCounterparty(cp);
      status.textContent = `Контрагент определён по договору: ${cp.name}${cp.role ? ` (${cp.role})` : ''}${how}. Проверьте и при необходимости поправьте.`;
    } else if (found && found.parties.length) {
      status.textContent = `Стороны найдены${how}, но какая из них ваша — не определено. Укажите контрагента кнопкой — вторая сторона станет «вашей компанией»:`;
      found.parties.forEach((party) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'button button--ghost button--small';
        button.textContent = `${party.name}${party.role ? ` — ${party.role}` : ''}`;
        button.addEventListener('click', () => {
          setCounterparty(party);
          const mine = found.parties.find((x) => x !== party);
          const fillCompany = mine && !$('#f-company').value.trim();
          if (fillCompany) $('#f-company').value = partyLine(mine);
          status.textContent = `Контрагент: ${party.name}.${fillCompany ? ' Ваша компания подставлена в «Дополнительно».' : ''}`;
          chips.hidden = true;
        });
        chips.append(button);
      });
      chips.hidden = false;
    } else {
      status.textContent = 'Стороны в начале договора не найдены. Выберите или введите контрагента.';
    }
  };

  const detect = async () => {
    const theirs = $('#f-theirs').files[0];
    show('');
    confirmBox.hidden = true;
    if (!theirs) {
      status.hidden = true;
      return;
    }
    status.hidden = false;
    status.textContent = 'Читаю договор…';
    const fd = new FormData();
    fd.append('theirs', theirs);
    fd.append('company', $('#f-company').value);
    try {
      fill(await contracts.detect(fd));
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        status.hidden = true;
        show(`Файл не подходит: ${(err.detail || '').replace(/: invalid argument$/, '') || err.message}`);
        return;
      }
      fill(null); // поиск сторон не удался — юрист вводит контрагента сам
      status.textContent = 'Не удалось определить контрагента автоматически. Выберите или введите его.';
    }
    if (!$('#f-project-name').value) $('#f-project-name').placeholder = stem(theirs.name);
    confirmBox.hidden = false;
  };
  wireDrops(detect);
  $('#f-project-name').addEventListener('input', () => { $('#f-project-name').dataset.touched = '1'; });
  $('#f-company').addEventListener('change', () => {
    if ($('#f-theirs').files[0]) detect();
  });

  wireReviewSubmit({
    form, submit: $('#review-submit'), progress: $('#review-progress'), show,
    collect() {
      const theirs = $('#f-theirs').files[0];
      if (!theirs) {
        show('Выберите файл первой версии договора (.docx, .odt или PDF).');
        return null;
      }
      if (!cpSelect.value && !$('#f-cp-name').value.trim()) {
        show('Укажите контрагента: выберите из списка или введите название.');
        $('#f-cp-name').focus();
        return null;
      }
      const select = $('#f-playbook');
      const role = select.selectedOptions[0] ? select.selectedOptions[0].dataset.role || '' : '';
      const confirm = $('#f-confirm').checked;
      memoSave({ our_authors: $('#f-authors').value, company: $('#f-company').value, playbook: select.value, confirm });
      const fd = new FormData();
      fd.append('theirs', theirs);
      fd.append('first_version', '1'); // правок в ней нет: положения проверяются по плейбуку (для PDF наша версия не нужна)
      fd.append('playbook', select.value);
      if (cpSelect.value) fd.append('counterparty_id', cpSelect.value);
      else {
        fd.append('counterparty_name', $('#f-cp-name').value);
        fd.append('counterparty_inn', $('#f-cp-inn').value);
      }
      fd.append('project_name', $('#f-project-name').value);
      fd.append('our_authors', $('#f-authors').value);
      fd.append('company', $('#f-company').value);
      return { fd, role, confirm };
    },
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
    mount($('#home'), html`<p class="alert">Не удалось загрузить данные. Обновите страницу чуть позже.</p>`);
  }
});
