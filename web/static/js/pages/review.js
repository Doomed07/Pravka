// Страница разбора: единая версия договора. Слева итог и список правок, в центре текст договора с правками,
// на полях — решение плейбука и пояснение. У разборов, сделанных до единой версии, — прежний отчёт.
import { ApiError, reviews } from '../api.js';
import { $, currentUser, errorView, html, mount, pathID, renderLayout, setTitle } from '../ui.js';

renderLayout({ nav: 'home', navDetail: true });

// ---------- Решение по правке ----------

function verdict(ch) {
  if (ch.lawyer_decision_needed) return { label: 'Решает юрист', mod: 'lawyer' };
  if ((ch.action || '').startsWith('Согласовано')) return { label: 'Согласовано', mod: 'agreed' };
  switch (ch.level) {
    case 'reject':
      return { label: 'Отклонить', mod: 'reject' };
    case 'fallback':
      return { label: 'Уступка', mod: 'fallback' };
    case 'accept':
      return { label: 'Принять', mod: 'accept' };
    default:
      return { label: 'Правка', mod: 'none' };
  }
}

const isSilent = (ch) => ch.source === 'silent' || ch.source === 'diff';
const fromBase = (ch) => (ch.accepted_from_base || []).length > 0;
const silentLabel = (ch) => (fromBase(ch) ? ' · из нашей версии' : ' · без отметки');

function num(n) {
  return String(n).padStart(2, '0');
}

function changeTitle(ch) {
  const where = ch.clause ? (/^\d/.test(ch.clause) ? `п. ${ch.clause}` : ch.clause) : 'без пункта';
  return ch.topic && ch.topic !== 'прочее' ? `${where} · ${ch.topic}` : where;
}

// ---------- Итог и список ----------

function summary(changes) {
  const count = (fn) => changes.filter(fn).length;
  const rows = [
    ['Отклонить', count((c) => c.level === 'reject' && !c.lawyer_decision_needed), true],
    ['Решает юрист', count((c) => c.lawyer_decision_needed), false],
    ['Уступка', count((c) => c.level === 'fallback' && !c.lawyer_decision_needed), false],
    ['Принять', count((c) => c.level === 'accept' && !c.lawyer_decision_needed), false],
    ['Без отметки', count(isSilent), true],
  ];
  return html`
    <div class="rv-sum" aria-label="Итог по плейбуку">
      ${rows.map(([label, n, hot]) => html`
        <div class="rv-sum__row"><span>${label}</span><span class="rv-sum__value${hot && n ? ' rv-sum__value--hot' : ''}">${n}</span></div>`)}
    </div>`;
}

function list(changes, order) {
  return html`
    <nav class="rv-list" aria-label="Правки по порядку">
      ${changes.map((ch) => html`
        <button class="rv-list__item${isSilent(ch) ? ' rv-list__item--silent' : ''}" type="button" data-change="${ch.id}">
          <span class="rv-list__num">${num(order.get(ch.id))}</span>
          <span class="rv-list__title">${changeTitle(ch)}</span>
          <span class="rv-list__level">${verdict(ch).label}${isSilent(ch) ? silentLabel(ch) : ''}</span>
        </button>`)}
    </nav>`;
}

// ---------- Примечание к правке ----------

function short(text, n = 90) {
  const t = (text || '').replace(/\s+/g, ' ').trim();
  return t.length > n ? t.slice(0, n - 1) + '…' : t;
}

// Кто написал карточку: правило программы или модель. Отличается от комментариев сторон (значок в тексте).
function noteBy(ch) {
  const by = ch.ai_explained ? 'пояснение ИИ' : ch.rule_id && ch.rule_id !== 'PARTY' ? 'по плейбуку' : 'проверка программы';
  return html`<p class="note__by"><span class="note__mark" aria-hidden="true">П</span>Правки · ${by}</p>`;
}

function note(ch, order) {
  const v = verdict(ch);
  const diff = ch.replaced_para
    ? html`<p class="note__diff">Пункт заменён новой редакцией${isSilent(ch) ? ' без отметки в рецензировании' : ''}.</p>`
    : fromBase(ch)
    ? html`<p class="note__diff">Принята правка из нашей версии (автор: ${ch.accepted_from_base.join(', ')}): было «${ch.before || '—'}», стало «${ch.after || '—'}».</p>`
    : isSilent(ch)
    ? html`<p class="note__diff">Изменено без отметки в рецензировании: было «${ch.before || '—'}», стало «${ch.after || '—'}».</p>`
    : ch.kind === 'comment'
      ? html`<p class="note__diff">Нужен ответ на комментарий (автор: ${ch.author || 'не указан'}): «${short(ch.after)}». Полный текст — по значку в тексте.</p>`
      : '';
  const carried = (ch.flags || []).includes('из прошлого раунда');
  return html`
    <article class="note${isSilent(ch) ? ' note--silent' : ''}" id="c-${ch.id}" data-change="${ch.id}">
      ${noteBy(ch)}
      <div class="note__head">
        <span class="note__id">${num(order.get(ch.id))} · ${changeTitle(ch)}</span>
        <span class="note__level note__level--${v.mod}">${v.label}</span>
      </div>
      ${carried ? html`<p><span class="tag tag--line">из прошлого раунда</span></p>` : ''}
      ${diff}
      ${ch.explanation ? html`<p>${ch.explanation}</p>` : ''}
      ${ch.suggested ? html`<p class="note__suggest">Наша позиция: ${ch.suggested}</p>` : ''}
      ${ch.escalate_to ? html`<p class="note__foot">Согласовать: ${ch.escalate_to}</p>` : ''}
      ${ch.rule_id && ch.rule_id !== 'PARTY' || isSilent(ch) ? html`<p class="note__foot">${[ch.rule_id && ch.rule_id !== 'PARTY' ? `правило ${ch.rule_id}` : '', isSilent(ch) ? 'найдено сравнением редакций' : ''].filter(Boolean).join(' · ')}</p>` : ''}
    </article>`;
}

// ---------- Комментарии сторон ----------

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('ru-RU');
}

function initials(name) {
  const parts = (name || '?').trim().split(/\s+/);
  return (parts[0][0] + (parts[1] ? parts[1][0] : '')).toUpperCase();
}

// Комментарии сторон из Word — целиком, но свёрнуты в значок, чтобы не мешать читать договор.
function partyComments(list) {
  if (!list || !list.length) return '';
  const label = `Комментарии сторон: ${list.length}`;
  return html`
    <details class="cmt">
      <summary class="cmt__badge" title="${label}" aria-label="${label}">
        <span class="cmt__icon" aria-hidden="true"></span>${list.length > 1 ? list.length : initials(list[0].author)}
      </summary>
      <div class="cmt__pop">
        ${list.map((c) => html`
          <div class="cmt__item">
            <p class="cmt__who"><span class="cmt__avatar${c.ours ? ' cmt__avatar--ours' : ''}">${initials(c.author)}</span>
              <span><b>${c.author || 'без имени'}</b>${c.ours ? ' · наш' : ''}<br><span class="cmt__date">${fmtDate(c.date)}</span></span></p>
            ${c.anchor ? html`<p class="cmt__anchor">к словам «${short(c.anchor, 80)}»</p>` : ''}
            <p class="cmt__text">${c.text}</p>
          </div>`)}
      </div>
    </details>`;
}

// ---------- Текст договора ----------

const SEGMENT = { ins: 'r-ins', del: 'r-del', silent_ins: 'r-silent-ins', silent_del: 'r-silent-del' };
const SEGMENT_LABEL = { ins: 'вставлено', del: 'удалено', silent_ins: 'вставлено без отметки', silent_del: 'удалено без отметки' };

function segment(s) {
  if (s.k === 'equal') return s.t;
  // ins/del — настоящие теги: экранные дикторы и копирование текста понимают правку
  const tag = s.k.endsWith('ins') ? 'ins' : 'del';
  return html`${tag === 'ins' ? html`<ins class="${SEGMENT[s.k]}" title="${SEGMENT_LABEL[s.k]}">${s.t}</ins>` : html`<del class="${SEGMENT[s.k]}" title="${SEGMENT_LABEL[s.k]}">${s.t}</del>`}`;
}

function isHeading(para, text) {
  const style = (para.style || '').toLowerCase();
  if (style.startsWith('heading') || style.startsWith('заголовок') || style === 'title') return true;
  return text.length < 90 && !/[.;:,]$/.test(text.trim()) && !/\./.test(para.clause || '') && !!para.clause;
}

// shown — правки, карточки которых уже нарисованы: замена пункта относится к двум абзацам, карточка одна.
function freshNotes(changes, order, shown) {
  return changes.filter((ch) => !shown.has(ch.id)).map((ch) => {
    shown.add(ch.id);
    return note(ch, order);
  });
}

function row(para, i, total, byID, order, shown) {
  const text = para.segments.map((s) => s.t).join('');
  const changes = para.changes.map((id) => byID.get(id)).filter(Boolean);
  const silent = para.segments.some((s) => s.k.startsWith('silent'));
  const changed = changes.length > 0 || para.segments.some((s) => s.k !== 'equal');
  const cls = ['doc__text'];
  if (isHeading(para, text) && !changed) cls.push('doc__text--head');
  if (silent) cls.push('doc__text--silent');
  else if (changed) cls.push('doc__text--changed');
  if (i === 0) cls.push('doc__text--first');
  if (i === total - 1) cls.push('doc__text--last');
  const first = changes[0];
  return html`
    <div class="doc__row">
      <div class="doc__num${first && verdict(first).mod === 'reject' ? ' doc__num--hot' : ''}">${first ? num(order.get(first.id)) : ''}</div>
      <div class="${cls.join(' ')}" id="p-${para.index >= 0 ? para.index : 'r' + i}" ${first ? html`data-change="${first.id}"` : ''}>
        ${para.label ? `${para.label} ` : ''}${para.segments.map(segment)}
        ${para.index < 0 ? html` <span class="tag tag--silent">абзац удалён без отметки</span>` : ''}
        ${partyComments(para.comments)}
      </div>
      <div class="doc__notes">${freshNotes(changes, order, shown)}</div>
    </div>`;
}

// Таблица из Word собирается обратно по координатам ячеек (table = [номер, строка, столбец, ширина]):
// один блок слева — вся таблица, справа — заметки ко всем её правкам.
function tableRow(paras, i, total, byID, order, shown) {
  const changes = paras.flatMap((p) => p.changes.map((id) => byID.get(id)).filter(Boolean));
  const changed = changes.length > 0 || paras.some((p) => p.segments.some((s) => s.k !== 'equal'));
  const silent = paras.some((p) => p.segments.some((s) => s.k.startsWith('silent')));
  const cls = ['doc__text', 'doc__text--table'];
  if (silent) cls.push('doc__text--silent');
  else if (changed) cls.push('doc__text--changed');
  if (i === 0) cls.push('doc__text--first');
  if (i === total - 1) cls.push('doc__text--last');
  const rows = new Map();
  for (const p of paras) {
    const [, r, c, span] = p.table;
    if (!rows.has(r)) rows.set(r, new Map());
    const cells = rows.get(r);
    if (!cells.has(c)) cells.set(c, { span: span || 1, paras: [] });
    cells.get(c).paras.push(p);
  }
  const first = changes[0];
  const body = [...rows.keys()].sort((a, b) => a - b).map((r) => {
    const cells = rows.get(r);
    return html`<tr>${[...cells.keys()].sort((a, b) => a - b).map((c) => {
      const cell = cells.get(c);
      return html`<td${cell.span > 1 ? html` colspan="${cell.span}"` : ''}>${cell.paras.map((p) => html`
        <p class="doc-table__p" id="p-${p.index}" ${p.changes[0] ? html`data-change="${p.changes[0]}"` : ''}>${p.label ? `${p.label} ` : ''}${p.segments.map(segment)}${partyComments(p.comments)}</p>`)}</td>`;
    })}</tr>`;
  });
  return html`
    <div class="doc__row">
      <div class="doc__num${first && verdict(first).mod === 'reject' ? ' doc__num--hot' : ''}">${first ? num(order.get(first.id)) : ''}</div>
      <div class="${cls.join(' ')}" ${first ? html`data-change="${first.id}"` : ''}>
        <table class="doc-table"><tbody>${body}</tbody></table>
      </div>
      <div class="doc__notes">${freshNotes(changes, order, shown)}</div>
    </div>`;
}

// blocks группирует подряд идущие абзацы одной таблицы в один блок.
function blocks(doc) {
  const out = [];
  for (const p of doc) {
    const last = out[out.length - 1];
    if (p.table && last && last.table && last.paras[0].table[0] === p.table[0]) last.paras.push(p);
    else out.push(p.table ? { table: true, paras: [p] } : { table: false, para: p });
  }
  return out;
}

function documentView(doc, changes, order) {
  const byID = new Map(changes.map((c) => [c.id, c]));
  const placed = new Set(doc.flatMap((p) => p.changes));
  const orphans = changes.filter((c) => !placed.has(c.id));
  const parts = blocks(doc);
  const shown = new Set();
  return html`
    <div class="doc">
      ${orphans.length ? html`
        <div class="doc__orphans">
          <p class="eyebrow">Без места в тексте: стороны, реквизиты, общие замечания</p>
          ${freshNotes(orphans, order, shown)}
        </div>` : ''}
      ${parts.map((b, i) => (b.table ? tableRow(b.paras, i, parts.length, byID, order, shown) : row(b.para, i, parts.length, byID, order, shown)))}
    </div>`;
}

// ---------- Страница ----------

function head(r, hasDocx) {
  return html`
    <header class="rv-head">
      <div>
        <p class="eyebrow">Единая версия договора</p>
        <h1 class="rv-head__title">${r.theirs_name}</h1>
        <p class="rv-head__meta">Наша редакция: ${r.base_name || 'не загружена'} · Плейбук: ${r.playbook_name || 'без плейбука'}${r.side ? html` · ${r.side}` : ''}</p>
      </div>
      <div class="rv-head__actions">
        ${hasDocx ? html`<a class="button button--cta" href="/api/v1/reviews/${r.id}/docx">Скачать Word с примечаниями</a>` : ''}
        <a class="button button--ghost" href="/api/v1/reviews/${r.id}/xlsx">Excel</a>
        <a class="button button--ghost" href="/api/v1/reviews/${r.id}/report" target="_blank" rel="noopener">Отчёт</a>
        <button class="button button--danger" type="button" id="delete">Удалить</button>
      </div>
    </header>`;
}

function unifiedView(r, doc, changes) {
  const order = new Map(changes.map((c, i) => [c.id, i + 1]));
  const warnings = r.warnings || [];
  return html`
    ${head(r, true)}
    <div class="rv">
      <aside class="rv-side">
        ${summary(changes)}
        ${changes.length ? list(changes, order) : html`<p class="empty-state">Правок не найдено.</p>`}
        <p class="legend">
          <span><ins class="r-ins">вставлено</ins></span>
          <span><del class="r-del">удалено</del></span>
          <span><span class="tag tag--silent">без отметки</span></span>
        </p>
      </aside>
      <div>
        ${warnings.length ? html`<div class="alert"><strong>Обратите внимание</strong><ul class="alert__list">${warnings.map((w) => html`<li>${w}</li>`)}</ul></div>` : ''}
        ${documentView(doc, changes, order)}
      </div>
    </div>`;
}

const TILES = [
  ['всего', 'Правок всего'],
  ['нужно решение юриста', 'Решает юрист'],
  ['красные линии', 'Красные линии'],
  ['тихие правки', 'Тихие правки'],
  ['комментарии', 'Комментарии'],
];

// legacyView — разборы, сделанные до появления единой версии: сводка и отчёт движка во встроенном окне.
function legacyView(r) {
  const c = r.counts || {};
  return html`
    ${head(r, false)}
    <p class="alert">Этот разбор сделан до появления единой версии договора. Чтобы получить её и файл Word с примечаниями, загрузите договор заново.</p>
    <dl class="tiles">
      ${TILES.map(([k, label]) => html`<div class="tiles__item"><dt>${label}</dt><dd>${c[k] ?? 0}</dd></div>`)}
    </dl>
    <p class="actions"></p>
    <iframe class="report-frame" src="/api/v1/reviews/${r.id}/report" title="Отчёт" sandbox=""></iframe>`;
}

// ---------- Поведение ----------

function select(id, scroll) {
  document.querySelectorAll('.is-current').forEach((el) => el.classList.remove('is-current'));
  const item = document.querySelector(`.rv-list__item[data-change="${CSS.escape(id)}"]`);
  const card = document.getElementById('c-' + id);
  const para = card ? card.closest('.doc__row')?.querySelector('.doc__text') : null; // для таблицы — вся таблица
  [item, card, para].forEach((el) => el && el.classList.add('is-current'));
  if (scroll === 'doc' && (para || card)) (para || card).scrollIntoView({ block: 'center' });
  if (scroll === 'list' && item) item.scrollIntoView({ block: 'nearest' });
}

function wire(id) {
  document.querySelectorAll('.rv-list__item').forEach((el) => {
    el.addEventListener('click', () => select(el.dataset.change, 'doc'));
  });
  document.querySelectorAll('.note, .doc__text[data-change]').forEach((el) => {
    el.addEventListener('click', () => select(el.dataset.change, 'list'));
  });

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

async function load() {
  const user = await currentUser();
  if (!user) {
    location.replace('/login?next=' + encodeURIComponent(location.pathname));
    return;
  }
  const id = pathID();
  const [r, doc, changes] = await Promise.all([reviews.get(id), reviews.document(id), reviews.changes(id)]);
  setTitle(r.theirs_name);
  const box = $('#review');
  box.classList.add('container--wide');
  const body = doc && doc.length ? unifiedView(r, doc, changes || []) : legacyView(r);
  mount(box, body);
  wire(id);
}

load().catch((err) => {
  if (!(err instanceof ApiError)) console.error(err);
  mount($('#review'), errorView(err instanceof ApiError ? err.status : 500));
});
