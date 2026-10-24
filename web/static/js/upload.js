// Отправка договора на разбор: общая для главной (первая версия) и страницы договора (новый раунд).
import { ApiError, reviews } from './api.js';

// wireReviewSubmit вешает отправку на форму. collect() собирает данные формы: {fd, role, confirm} или null, если форма
// заполнена не полностью (сообщение показывает сама collect через show). Роль плейбука, не подтверждённая движком (422),
// запоминается: повторное нажатие подтверждает её вручную.
export function wireReviewSubmit({ form, submit, progress, show, collect }) {
  let confirmRole = ''; // роль, которую юрист подтвердил после ответа 422
  const label = submit.textContent;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    show('');
    const built = collect();
    if (!built) return;
    const { fd, role, confirm } = built;
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
        show(`Сторона договора не подтверждена: ${err.message} Если вы действительно «${err.data.role}», нажмите кнопку ещё раз — роль будет подтверждена вручную.`);
        submit.textContent = `Подтвердить роль «${err.data.role}» и разобрать →`;
      } else if (status === 400) {
        // текст ошибки проверки (неверный файл, роль не совпала с прошлыми раундами) — для юриста, без служебного хвоста
        show(`Не удалось разобрать: ${(err.detail || '').replace(/: invalid argument$/, '') || err.message}`);
        submit.textContent = label;
      } else if (status === 409) {
        show('Такой контрагент уже есть. Выберите его в списке.');
      } else if (status === 502) {
        show('Движок разбора не отвечает. Проверьте, что контейнер engine запущен, и попробуйте ещё раз.');
      } else if (status === 401) {
        location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
      } else {
        show('Не удалось выполнить разбор. Попробуйте ещё раз чуть позже.');
      }
      submit.disabled = false;
      progress.hidden = true;
    }
  });
}

// Поля, которые удобно не вводить каждый раз. Хранятся только в этом браузере; сбой хранилища не мешает работе.
const MEMO = 'pravki.form';
export function memoLoad() {
  try {
    return JSON.parse(localStorage.getItem(MEMO) || '{}');
  } catch {
    return {};
  }
}
export function memoSave(v) {
  try {
    localStorage.setItem(MEMO, JSON.stringify({ ...memoLoad(), ...v }));
  } catch {
    /* приватный режим и т.п. */
  }
}

// Зоны загрузки: показать имя выбранного файла и подсветить зону, когда над ней держат файл.
export function wireDrops(onChange) {
  document.querySelectorAll('.drop').forEach((drop) => {
    const input = drop.querySelector('input');
    const label = drop.querySelector('.drop__file');
    const show = () => {
      const f = input.files[0];
      label.textContent = f ? f.name : label.dataset.empty;
      drop.classList.toggle('has-file', !!f);
    };
    input.addEventListener('change', () => {
      show();
      if (onChange) onChange(input);
    });
    input.addEventListener('dragenter', () => drop.classList.add('is-over'));
    ['dragleave', 'drop'].forEach((e) => input.addEventListener(e, () => drop.classList.remove('is-over')));
    show();
  });
}

export function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
  } catch {
    return iso;
  }
}
