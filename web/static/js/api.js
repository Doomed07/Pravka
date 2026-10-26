// Обёртка над JSON API /api/v1.

export class ApiError extends Error {
  // detail — технический текст ошибки от сервера (поле "error"); по нему формы
  // отличают «имя занято» от «email занят». Пользователю его не показываем.
  constructor(status, message, detail = '') {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

// query собирает строку параметров, пропуская пустые значения: {title: null, limit: 37} → "?limit=37".
export function query(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, value);
  }
  const s = search.toString();
  return s ? '?' + s : '';
}

export async function api(path, { method = 'GET', body } = {}) {
  let response;
  try {
    response = await fetch('/api/v1' + path, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network error');
  }

  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }

  if (!response.ok) {
    throw new ApiError(response.status, (data && data.message) || response.statusText, (data && data.error) || '');
  }
  return data;
}

// ---------- Аккаунт ----------
// Сессия живёт в HttpOnly-cookie: JS её не видит, браузер сам прикладывает её к запросам.

export const auth = {
  register: (username, email, password, invite_code) =>
    api('/auth/register', { method: 'POST', body: { username, email, password, invite_code } }),

  login: (login, password) => api('/auth/login', { method: 'POST', body: { login, password } }),

  // Тело {} нужно ради заголовка Content-Type: application/json: без него сервер
  // отклонит запрос (защита от подделки запросов с чужих сайтов).
  logout: () => api('/auth/logout', { method: 'POST', body: {} }),

  // me — вошедший пользователь или null, если не вошёл (401 здесь не ошибка).
  async me() {
    try {
      return await api('/auth/me');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return null;
      throw err;
    }
  },
};

// ---------- Разборы договоров ----------

// upload отправляет форму с файлами. Заголовок X-Requested-With: pravki нужен серверу, чтобы отличить
// нашу загрузку от формы, подброшенной чужим сайтом (защита от подделки запросов).
export async function upload(path, formData) {
  let response;
  try {
    response = await fetch('/api/v1' + path, { method: 'POST', headers: { 'X-Requested-With': 'pravki' }, body: formData });
  } catch {
    throw new ApiError(0, 'network error');
  }
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    const err = new ApiError(response.status, (data && data.message) || response.statusText, (data && data.error) || '');
    err.data = data;
    throw err;
  }
  return data;
}

export const reviews = {
  playbooks: () => api('/playbooks'),
  list: (limit = 21, offset = 0) => api('/reviews' + query({ limit, offset })),
  get: (id) => api('/reviews/' + id),
  document: (id) => api('/reviews/' + id + '/document'),
  changes: (id) => api('/reviews/' + id + '/changes'),
  // сводка раунда по темам (собирается из правок, без модели)
  summary: (id) => api('/reviews/' + id + '/summary'),
  // как правки связаны с прошлыми раундами того же договора: повторные, возвращения к пункту, снятые
  rounds: (id) => api('/reviews/' + id + '/rounds'),
  choices: (id) => api('/reviews/' + id + '/choices'),
  // «как решали раньше»: прошлые решения юриста по похожим правкам
  precedents: (id) => api('/reviews/' + id + '/precedents'),
  // «что говорит ГК»: ближайшие по смыслу пункты ГК РФ к правкам (при первом открытии считается несколько секунд)
  law: (id) => api('/reviews/' + id + '/law'),
  // «ваши прошлые формулировки»: похожие пункты нашей редакции из прошлых разборов
  wordings: (id) => api('/reviews/' + id + '/wordings'),
  // пустой choice снимает решение
  saveChoice: (id, change, choice, text = '') =>
    api('/reviews/' + id + '/choices/' + encodeURIComponent(change), { method: 'PUT', body: { choice, text } }),
  answer: (id, author) => answerFile(id, author),
  create: (formData) => upload('/reviews', formData),
  remove: (id) => api('/reviews/' + id, { method: 'DELETE' }),
};

// Договоры (проекты): разборы одного договора — его раунды.
export const projects = {
  list: () => api('/projects'),
  get: (id) => api('/projects/' + id),
  // перенести договор к другому контрагенту (папка договора на диске остаётся прежней)
  move: (id, counterpartyID) => api('/projects/' + id, { method: 'PATCH', body: { counterparty_id: counterpartyID } }),
  // удалить договор со всеми раундами; файлы на диске остаются
  remove: (id) => api('/projects/' + id, { method: 'DELETE' }),
};

// Контрагенты: у контрагента — договоры, у договора — раунды.
export const counterparties = {
  list: () => api('/counterparties'),
  get: (id) => api('/counterparties/' + id),
  update: (id, name, inn) => api('/counterparties/' + id, { method: 'PATCH', body: { name, inn } }),
};

export const contracts = {
  // стороны договора и контрагент по первой версии (ничего не сохраняет); company — наш ИНН или наименование
  detect: (formData) => upload('/contracts/detect', formData),
};

// answerFile скачивает ответ контрагенту в Word: {blob, stats}. Файл собирается на сервере по решениям юриста.
async function answerFile(id, author) {
  let response;
  try {
    response = await fetch('/api/v1/reviews/' + id + '/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ author }),
    });
  } catch {
    throw new ApiError(0, 'network error');
  }
  if (!response.ok) {
    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    throw new ApiError(response.status, (data && data.message) || response.statusText, (data && data.error) || '');
  }
  const stats = {};
  for (const k of ['accept', 'reject', 'counter', 'reply', 'edit', 'comment', 'untracked']) stats[k] = Number(response.headers.get('X-Pravki-' + k) || 0);
  return { blob: await response.blob(), stats };
}
