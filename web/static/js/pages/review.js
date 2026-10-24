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

// ---------- Сводка раунда ----------

// Порядок и подписи выводов плейбука в строке темы: сначала то, что требует внимания.
const ROUND_VERDICTS = [
  ['reject', 'Отклонить', true],
  ['lawyer', 'Решает юрист', true],
  ['fallback', 'Уступка', false],
  ['agreed', 'Согласовано', false],
  ['accept', 'Принять', false],
  ['none', 'Без вывода', false],
];
const VERDICT_LABEL = Object.fromEntries(ROUND_VERDICTS.map(([k, label]) => [k, label]));

// Что сделал контрагент — только из текста правки, без пересказа.
function roundWhat(it) {
  switch (it.kind) {
    case 'comment':
      return `комментарий: «${it.after}»`;
    case 'insert':
      return `добавлено «${it.after}»`;
    case 'delete':
      return `удалено «${it.before}»`;
    case 'para_insert':
      return `новый пункт: «${it.after}»`;
    case 'para_delete':
      return `удалён пункт: «${it.before}»`;
    default:
      return `«${it.before || '—'}» → «${it.after || '—'}»`;
  }
}

function roundCounts(t) {
  const parts = ROUND_VERDICTS.filter(([k]) => t.verdicts[k]).map(([k, label, hot]) =>
    html`<span class="round__count${hot ? ' round__count--hot' : ''}">${label} ${t.verdicts[k]}</span>`);
  if (t.silent) parts.push(html`<span class="round__count round__count--silent">без отметки ${t.silent}</span>`);
  if (t.deleted) parts.push(html`<span class="round__count">удалено ${t.deleted}</span>`);
  return parts;
}

function roundView(sum) {
  if (!sum || !sum.topics.length) return '';
  return html`
    <section class="round" aria-labelledby="round-title">
      <div class="round__head">
        <h2 class="round__title" id="round-title">Сводка раунда</h2>
        <p class="round__meta">Тем: ${sum.topics.length}${sum.technical ? html` · технических правок: ${sum.technical}` : ''}</p>
      </div>
      ${sum.topics.map((t) => html`
        <details class="round__topic">
          <summary class="round__summary">
            <span class="round__name">${t.topic}</span>
            <span class="round__counts">${roundCounts(t)}</span>
          </summary>
          <ul class="round__items">
            ${t.items.map((it) => html`
              <li><button class="round__item" type="button" data-change="${it.change_id}">
                <span class="round__where">${it.clause ? (/^\d/.test(it.clause) ? `п. ${it.clause}` : it.clause) : 'без пункта'}</span>
                <span class="round__what">${roundWhat(it)}</span>
                <span class="round__verdict">${VERDICT_LABEL[it.verdict] || ''}${it.silent ? ' · без отметки' : ''}</span>
              </button></li>`)}
          </ul>
        </details>`)}
    </section>`;
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

// ---------- Решение юриста по правке (пошаговый просмотр) ----------

// Решения, сохранённые на сервере: id правки → {choice, text}. Загружаются до отрисовки.
const CHOICES = new Map();

const DECISIONS = [
  ['accept', 'Принять'],
  ['reject', 'Отклонить'],
  ['counter', 'Встречная редакция'],
];

// Подсказка программы: какое решение соответствует выводу плейбука. Юрист выбирает сам.
function hinted(ch) {
  if (ch.lawyer_decision_needed) return '';
  if (ch.level === 'accept' || ch.level === 'fallback') return 'accept';
  if (ch.level === 'reject') return ch.suggested ? 'counter' : 'reject';
  return '';
}

// Ответ на комментарий контрагента: попадёт в Word в ту же ветку примечаний. Пустой ответ — решения нет.
function replyBlock(ch) {
  const cur = CHOICES.get(ch.id) || {};
  return html`
    <div class="decide decide--reply" data-change="${ch.id}">
      <label class="decide__label" for="reply-${ch.id}">Ваш ответ на комментарий</label>
      <textarea class="decide__text form__input" id="reply-${ch.id}" rows="3" maxlength="5000"
        placeholder="Попадёт в Word ответом в той же ветке комментариев">${cur.choice === 'reply' ? cur.text : ''}</textarea>
      <p class="decide__status" role="status"></p>
    </div>`;
}

// ---------- Раунды договора ----------

// Связь правок с прошлыми раундами: id правки → {relation, round, review_id, past_change_id, decision…}. Только подсказка.
const LINKS = new Map();
let ROUNDS = null;

function roundMark(ch) {
  const l = LINKS.get(ch.id);
  if (!l || l.relation === 'new') return '';
  const past = `/reviews/${l.review_id}#c-${l.past_change_id}`;
  const decided = l.decision ? ` · вы ${PAST_CHOICE[l.decision] || l.decision}` : '';
  const text = l.decision === 'counter' && l.decision_text ? html` — «${short(l.decision_text, 120)}»` : '';
  return l.relation === 'repeat'
    ? html`<p class="round-mark"><b>Повторная правка</b> · <a href="${past}">раунд ${l.round}</a>${decided}${text}</p>`
    : html`<p class="round-mark round-mark--returned"><b>Контрагент вернулся к пункту</b> · в <a href="${past}">раунде ${l.round}</a> было «${short(l.past_before, 50) || '—'}» → «${short(l.past_after, 50) || '—'}»${decided}${text}</p>`;
}

function roundBar(r) {
  if (!ROUNDS) return '';
  const n = (rel) => ROUNDS.links.filter((l) => l.relation === rel).length;
  const closed = ROUNDS.closed || [];
  const parts = ROUNDS.round > 1
    ? [`новых ${n('new')}`, `повторных ${n('repeat')}`, `вернулись к пункту ${n('returned')}`, `снято контрагентом ${closed.length}`]
    : [];
  return html`
    <section class="round-bar" aria-label="Раунд договора">
      <p class="round-bar__line"><b>Раунд ${ROUNDS.round}</b> по договору «${ROUNDS.project.name}»${parts.length ? html`: ${parts.join(' · ')}` : ''}</p>
      <p class="round-bar__actions">
        <a href="/projects/${ROUNDS.project.id}">История договора</a>
        <a class="button button--ghost" href="/?project=${ROUNDS.project.id}">Следующий раунд</a>
      </p>
      ${closed.length ? html`
        <details class="round-bar__closed">
          <summary>Что контрагент снял с прошлого раунда: ${closed.length}</summary>
          <ul class="past__list">
            ${closed.map((c) => html`<li class="past__item">
              <p class="past__head">${c.clause ? `п. ${c.clause} · ` : ''}${c.topic || 'без темы'} · <a href="/reviews/${c.review_id}#c-${c.change_id}">раунд ${c.round}</a></p>
              <p class="past__diff">было «${short(c.before, 60) || '—'}», стало «${short(c.after, 60) || '—'}»</p>
              <p class="past__choice">${c.decision ? `Ваше решение: ${PAST_CHOICE[c.decision] || c.decision}` : 'Вы не решали'}${c.decision === 'counter' && c.decision_text ? html` — «${short(c.decision_text, 120)}»` : ''}</p>
            </li>`)}
          </ul>
        </details>` : ''}
    </section>`;
}

// ---------- Как решали раньше ----------

// Прошлые решения юриста по похожим правкам: id правки → список. Только подсказка: решает юрист.
const PRECEDENTS = new Map();

const PAST_CHOICE = { accept: 'приняли', reject: 'отклонили', counter: 'встречная редакция' };

function precedentItem(p) {
  const kind = p.same ? 'Та же правка' : p.semantic ? 'Похожая по смыслу' : 'Похожая правка';
  return html`
    <li class="past__item">
      <p class="past__head"><b>${kind}</b> · <a href="/reviews/${p.review_id}#c-${p.past_change}">${short(p.theirs_name, 40)}</a>, ${fmtDate(p.created_at)}</p>
      <p class="past__diff">было «${short(p.before, 60) || '—'}», стало «${short(p.after, 60) || '—'}»</p>
      <p class="past__choice">Решение: ${PAST_CHOICE[p.choice] || p.choice}${p.choice === 'counter' && p.text ? html` — «${short(p.text, 160)}»` : ''}</p>
      ${p.choice === 'counter' && p.text ? html`<button class="past__use" type="button" data-text="${p.text}">Взять эту формулировку</button>` : ''}
    </li>`;
}

function precedentsBlock(ch) {
  const list = PRECEDENTS.get(ch.id);
  if (!list || !list.length || ch.kind === 'comment') return '';
  return html`
    <details class="past"${list[0].same ? ' open' : ''}>
      <summary class="past__title">Как решали раньше: ${list.length}</summary>
      <ul class="past__list">${list.map(precedentItem)}</ul>
      <p class="past__foot">Из ваших прошлых разборов того же вида договора. Подсказка, решаете вы.</p>
    </details>`;
}

// ---------- Что говорит ГК ----------

function lawRef(h) {
  return `ст. ${h.article}${h.point ? ` п. ${h.point}` : ''} ГК РФ`;
}

function lawBlock(hints) {
  return html`
    <details class="law">
      <summary class="law__title">Что говорит ГК: ${hints.map(lawRef).join('; ')}</summary>
      <ul class="law__list">
        ${hints.map((h) => html`
          <li class="law__item">
            <p class="law__head"><b>${lawRef(h)}</b> · ${h.title}${h.edited ? html` <span class="law__ed">(ред. от ${fmtDate(h.edited)})</span>` : ''}</p>
            <p class="law__text">${h.text}</p>
          </li>`)}
      </ul>
      <p class="law__foot">Подобрано по смыслу из ГК РФ (pravo.gov.ru). Подсказка: применимость нормы оценивает юрист.</p>
    </details>`;
}

// ---------- Ваши прошлые формулировки ----------

function wordingsBlock(list) {
  return html`
    <details class="past past--wording">
      <summary class="past__title">Ваши прошлые формулировки: ${list.length}</summary>
      <ul class="past__list">
        ${list.map((w) => html`
          <li class="past__item">
            <p class="past__head">${w.clause ? `п. ${w.clause} · ` : ''}<a href="/reviews/${w.review_id}">${short(w.theirs_name, 40)}</a>, ${fmtDate(w.created_at)}</p>
            <p>«${w.text}»</p>
            <button class="past__use" type="button" data-text="${w.text}">Взять эту формулировку</button>
          </li>`)}
      </ul>
      <p class="past__foot">Пункты вашей редакции из прошлых разборов того же вида договора. Подсказка, решаете вы.</p>
    </details>`;
}

// Кнопка «Взять эту формулировку»: встречная редакция с этим текстом, юрист может поправить. Блоки с кнопками
// приходят и после отрисовки (формулировки), поэтому обработчик — один на документ.
function wireUse(id, refresh) {
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest && e.target.closest('.past__use');
    if (!btn) return;
    e.stopPropagation();
    const box = btn.closest('.note')?.querySelector('.decide');
    if (!box) return;
    const text = box.querySelector('.decide__text');
    text.value = btn.dataset.text;
    text.hidden = false;
    box.querySelectorAll('.decide__btn').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.choice === 'counter')));
    await saveChoice(id, box, 'counter', text.value);
    refresh();
    text.focus();
  });
}

async function loadWordings(id) {
  let list = [];
  try {
    list = (await reviews.wordings(id)) || [];
  } catch {
    return;
  }
  const by = new Map();
  for (const w of list) {
    if (!by.has(w.change_id)) by.set(w.change_id, []);
    by.get(w.change_id).push(w);
  }
  for (const [change, items] of by) {
    const slot = document.querySelector(`.wording-slot[data-change="${CSS.escape(change)}"]`);
    if (slot) mount(slot, wordingsBlock(items));
  }
}

// Подсказки по ГК приходят после отрисовки страницы: место для них — пустой блок в карточке правки.
async function loadLaw(id) {
  let hints = [];
  try {
    hints = (await reviews.law(id)) || [];
  } catch {
    return; // без подсказок по ГК страница работает как раньше
  }
  const by = new Map();
  for (const h of hints) {
    if (!by.has(h.change_id)) by.set(h.change_id, []);
    by.get(h.change_id).push(h);
  }
  for (const [change, list] of by) {
    const slot = document.querySelector(`.law-slot[data-change="${CSS.escape(change)}"]`);
    if (slot) mount(slot, lawBlock(list));
  }
}

function decideBlock(ch) {
  if (ch.kind === 'comment') return replyBlock(ch);
  const cur = CHOICES.get(ch.id) || {};
  const hint = hinted(ch);
  const party = ch.rule_id === 'PARTY' && !(ch.revs || []).length; // сверка сторон: правится в тексте вручную
  return html`
    <div class="decide" data-change="${ch.id}">
      <div class="decide__buttons" role="group" aria-label="Решение по правке">
        ${DECISIONS.map(([k, label]) => html`
          <button class="decide__btn${k === hint ? ' decide__btn--hint' : ''}" type="button" data-choice="${k}"
            aria-pressed="${cur.choice === k ? 'true' : 'false'}"${k === hint ? html` title="Совпадает с выводом программы"` : ''}>${label}</button>`)}
      </div>
      <textarea class="decide__text form__input" rows="3" maxlength="5000"${cur.choice === 'counter' ? '' : ' hidden'}
        placeholder="${ch.suggested ? `Ваша редакция. Позиция плейбука: ${ch.suggested}` : 'Ваша редакция'}">${cur.text || ''}</textarea>
      ${party ? html`<p class="decide__note">Это итог сверки сторон: решение сохранится, а реквизиты в ответе правьте вручную.</p>` : ''}
      <p class="decide__status" role="status"></p>
    </div>`;
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
      ${roundMark(ch)}
      ${diff}
      ${ch.explanation ? html`<p>${ch.explanation}</p>` : ''}
      ${ch.suggested ? html`<p class="note__suggest">Наша позиция: ${ch.suggested}</p>` : ''}
      ${ch.escalate_to ? html`<p class="note__foot">Согласовать: ${ch.escalate_to}</p>` : ''}
      ${ch.rule_id && ch.rule_id !== 'PARTY' || isSilent(ch) ? html`<p class="note__foot">${[ch.rule_id && ch.rule_id !== 'PARTY' ? `правило ${ch.rule_id}` : '', isSilent(ch) ? 'найдено сравнением редакций' : ''].filter(Boolean).join(' · ')}</p>` : ''}
      ${precedentsBlock(ch)}
      <div class="wording-slot" data-change="${ch.id}"></div>
      <div class="law-slot" data-change="${ch.id}"></div>
      ${decideBlock(ch)}
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

// Жирный и курсив — как в Word (b, i у куска текста).
function styled(s, inner) {
  let out = inner;
  if (s.i) out = html`<i>${out}</i>`;
  if (s.b) out = html`<b>${out}</b>`;
  return out;
}

function segment(s) {
  if (s.k === 'equal') return styled(s, s.t);
  // ins/del — настоящие теги: экранные дикторы и копирование текста понимают правку
  const tag = s.k.endsWith('ins') ? 'ins' : 'del';
  return html`${tag === 'ins' ? html`<ins class="${SEGMENT[s.k]}" title="${SEGMENT_LABEL[s.k]}">${styled(s, s.t)}</ins>` : html`<del class="${SEGMENT[s.k]}" title="${SEGMENT_LABEL[s.k]}">${styled(s, s.t)}</del>`}`;
}

// Заголовок — только по стилю Word. Жирность берётся из самого документа (b у кусков), а не угадывается.
function isHeading(para) {
  const style = (para.style || '').toLowerCase();
  return style.startsWith('heading') || style.startsWith('заголовок') || style === 'title';
}

const BULLETS = ['•', '◦', '▪'];

// Вид абзаца из Word: отступ слева (твипы → px), уровень списка, выравнивание, маркер.
function layout(para) {
  const level = para.list ? para.level || 0 : 0;
  const px = Math.min(160, Math.round((para.indent || 0) / 15) || (para.list ? 24 * (level + 1) : 0));
  const style = [px ? `padding-left: calc(24px + ${px}px)` : '', para.align ? `text-align: ${para.align === 'both' ? 'justify' : para.align}` : '']
    .filter(Boolean).join('; ');
  const marker = para.list === 'bullet' ? html`<span class="doc__bullet" aria-hidden="true">${BULLETS[level % BULLETS.length]}</span>` : '';
  return { style, marker };
}

// shown — правки, карточки которых уже нарисованы: замена пункта относится к двум абзацам, карточка одна.
function freshNotes(changes, order, shown) {
  return changes.filter((ch) => !shown.has(ch.id)).map((ch) => {
    shown.add(ch.id);
    return note(ch, order);
  });
}

function row(para, i, total, byID, order, shown) {
  const changes = para.changes.map((id) => byID.get(id)).filter(Boolean);
  const silent = para.segments.some((s) => s.k.startsWith('silent'));
  const changed = changes.length > 0 || para.segments.some((s) => s.k !== 'equal');
  const cls = ['doc__text'];
  if (isHeading(para) && !changed) cls.push('doc__text--head');
  if (para.list) cls.push('doc__text--list');
  const look = layout(para);
  if (silent) cls.push('doc__text--silent');
  else if (changed) cls.push('doc__text--changed');
  if (i === 0) cls.push('doc__text--first');
  if (i === total - 1) cls.push('doc__text--last');
  const first = changes[0];
  return html`
    <div class="doc__row">
      <div class="doc__num${first && verdict(first).mod === 'reject' ? ' doc__num--hot' : ''}">${first ? num(order.get(first.id)) : ''}</div>
      <div class="${cls.join(' ')}" id="p-${para.index >= 0 ? para.index : 'r' + i}" ${first ? html`data-change="${first.id}"` : ''}${look.style ? html` style="${look.style}"` : ''}>
        ${look.marker}${para.label ? `${para.label} ` : ''}${para.segments.map(segment)}
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
        <p class="doc-table__p" id="p-${p.index}" ${p.changes[0] ? html`data-change="${p.changes[0]}"` : ''}>${p.list === 'bullet' ? '• ' : ''}${p.label ? `${p.label} ` : ''}${p.segments.map(segment)}${partyComments(p.comments)}</p>`)}</td>`;
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
        <p class="eyebrow">${r.project_name ? `${r.project_name} · раунд ${r.round}` : 'Единая версия договора'}</p>
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

// Сколько правок и комментариев уже решено (у комментария решение — ответ).
function decidedCount(changes) {
  return [changes.filter((c) => CHOICES.has(c.id)).length, changes.length];
}

const AUTHOR_KEY = 'pravki.answer.author';

function defaultAuthor() {
  try {
    const saved = localStorage.getItem(AUTHOR_KEY);
    if (saved) return saved;
    const memo = JSON.parse(localStorage.getItem('pravki.form') || '{}');
    return (memo.our_authors || '').split(',')[0].trim();
  } catch {
    return '';
  }
}

// Файл контрагента не .docx (.odt или PDF): единая версия и ответ собираются из Word-файла, поэтому только для .docx.
function noWordNote() {
  return html`
    <section class="answer" aria-label="Word недоступен">
      <h2 class="answer__title">Word недоступен</h2>
      <p class="answer__progress">Файл контрагента не .docx: Word с примечаниями и ответ контрагенту в Word собираются только из .docx.
      Решения по правкам сохраняются, отчёт и Excel доступны.</p>
    </section>`;
}

function answerPanel(changes) {
  const [done, total] = decidedCount(changes);
  return html`
    <section class="answer" aria-labelledby="answer-title">
      <h2 class="answer__title" id="answer-title">Ответ контрагенту</h2>
      <p class="answer__progress" id="answer-progress">Решено ${done} из ${total}</p>
      <label class="form__label" for="answer-author">Автор наших правок в Word</label>
      <input class="form__input" id="answer-author" maxlength="100" value="${defaultAuthor()}" placeholder="как вы подписаны в Word">
      <button class="button button--cta" type="button" id="answer-build">Собрать ответ в Word</button>
      <p class="answer__status" id="answer-status" role="status"></p>
    </section>`;
}

function unifiedView(r, doc, changes, sum) {
  const order = new Map(changes.map((c, i) => [c.id, i + 1]));
  const warnings = r.warnings || [];
  return html`
    ${head(r, r.has_docx)}
    ${roundBar(r)}
    ${roundView(sum)}
    <div class="rv">
      <aside class="rv-side">
        ${r.has_docx ? answerPanel(changes) : noWordNote()}
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

function setStatus(el, text) {
  if (el) el.textContent = text;
}

async function saveChoice(id, box, choice, text) {
  const status = box.querySelector('.decide__status');
  setStatus(status, 'Сохраняю…');
  try {
    await reviews.saveChoice(id, box.dataset.change, choice, choice === 'counter' || choice === 'reply' ? text : '');
    if (choice) CHOICES.set(box.dataset.change, { choice, text });
    else CHOICES.delete(box.dataset.change);
    setStatus(status, choice ? 'Сохранено' : 'Решение снято');
  } catch (err) {
    setStatus(status, err instanceof ApiError && err.status === 400 ? 'Не сохранено: проверьте текст' : 'Не сохранено, попробуйте ещё раз');
  }
}

function wireDecisions(id, changes) {
  const progress = $('#answer-progress');
  const refresh = () => {
    const [done, total] = decidedCount(changes);
    setStatus(progress, `Решено ${done} из ${total}`);
  };
  document.querySelectorAll('.decide').forEach((box) => {
    const text = box.querySelector('.decide__text');
    box.addEventListener('click', (e) => e.stopPropagation()); // клик по решению не прокручивает страницу
    box.querySelectorAll('.decide__btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const again = btn.getAttribute('aria-pressed') === 'true'; // повторное нажатие снимает решение
        const choice = again ? '' : btn.dataset.choice;
        box.querySelectorAll('.decide__btn').forEach((b) => b.setAttribute('aria-pressed', String(b === btn && !again)));
        text.hidden = choice !== 'counter';
        if (choice === 'counter') text.focus();
        await saveChoice(id, box, choice, text.value);
        refresh();
      });
    });
    let timer;
    const reply = box.classList.contains('decide--reply');
    text.addEventListener('input', () => {
      clearTimeout(timer);
      // у комментария решение — сам ответ: пустое поле снимает решение
      const choice = reply ? (text.value.trim() ? 'reply' : '') : 'counter';
      timer = setTimeout(async () => {
        await saveChoice(id, box, choice, text.value);
        refresh();
      }, 700);
    });
  });

  wireUse(id, refresh);

  const build = $('#answer-build');
  const author = $('#answer-author');
  const status = $('#answer-status');
  if (!build) return; // у разбора не из .docx панели ответа нет
  build.addEventListener('click', async () => {
    try {
      localStorage.setItem(AUTHOR_KEY, author.value.trim());
    } catch {
      /* приватный режим */
    }
    build.disabled = true;
    setStatus(status, 'Собираю…');
    try {
      const { blob, stats } = await reviews.answer(id, author.value.trim());
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `Ответ_контрагенту_${id}.docx`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      const skipped = stats.untracked ? ` Не вошли в файл (правки без отметки): ${stats.untracked}.` : '';
      setStatus(status, `Готово: принято ${stats.accept}, отклонено ${stats.reject}, встречных редакций ${stats.counter}, ответов на комментарии ${stats.reply}.${skipped} Черновик — проверьте перед отправкой, дисклеймер в конце отклоните.`);
    } catch (err) {
      setStatus(status, err instanceof ApiError && err.status === 404
        ? 'Для этого разбора ответ собрать нельзя: загрузите договор заново.'
        : 'Не удалось собрать ответ. Попробуйте ещё раз.');
    } finally {
      build.disabled = false;
    }
  });
}

function wire(id) {
  document.querySelectorAll('.rv-list__item, .round__item').forEach((el) => {
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
  const [r, doc, changes, choices, precedents, sum, rounds] = await Promise.all([reviews.get(id), reviews.document(id),
    reviews.changes(id), reviews.choices(id).catch(() => []), reviews.precedents(id).catch(() => []),
    reviews.summary(id).catch(() => null), reviews.rounds(id).catch(() => null)]);
  ROUNDS = rounds;
  LINKS.clear();
  for (const l of (rounds && rounds.links) || []) LINKS.set(l.change_id, l);
  PRECEDENTS.clear();
  for (const p of precedents || []) {
    if (!PRECEDENTS.has(p.change_id)) PRECEDENTS.set(p.change_id, []);
    PRECEDENTS.get(p.change_id).push(p);
  }
  CHOICES.clear();
  for (const c of choices || []) CHOICES.set(c.change_id, { choice: c.choice, text: c.text });
  setTitle(r.theirs_name);
  const box = $('#review');
  box.classList.add('container--wide');
  const body = doc && doc.length ? unifiedView(r, doc, changes || [], sum) : legacyView(r);
  mount(box, body);
  wire(id);
  if (doc && doc.length) {
    wireDecisions(id, changes || []);
    loadWordings(id);
    loadLaw(id);
  }
  // ссылка из «как решали раньше» ведёт к правке прошлого разбора: /reviews/3#c-E001
  const target = decodeURIComponent(location.hash.slice(1));
  if (target.startsWith('c-') && document.getElementById(target)) select(target.slice(2), 'doc');
}

load().catch((err) => {
  if (!(err instanceof ApiError)) console.error(err);
  mount($('#review'), errorView(err instanceof ApiError ? err.status : 500));
});
