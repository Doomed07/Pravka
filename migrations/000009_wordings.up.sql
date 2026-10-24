-- «Ваши прошлые формулировки» и «как решали раньше» по смыслу: абзацы нашей редакции из прошлых разборов с векторами
-- (bge-m3) и отметка, что разбор проиндексирован (векторы абзацев и правок посчитаны). Индекс по вектору не нужен:
-- поиск идёт только по разборам одного юриста, точный перебор быстрее и не теряет результаты из-за фильтров.
ALTER TABLE pravkiapp.reviews ADD COLUMN indexed_at TIMESTAMPTZ;

CREATE TABLE pravkiapp.review_paragraphs (
    review_id INT NOT NULL REFERENCES pravkiapp.reviews(id) ON DELETE CASCADE,
    idx       INT NOT NULL,                     -- номер абзаца в файле контрагента; < 0 — абзац удалён контрагентом
    clause    VARCHAR(50) NOT NULL DEFAULT '',
    text      TEXT NOT NULL,                    -- абзац в нашей редакции
    model     VARCHAR(100) NOT NULL,
    embedding vector(1024) NOT NULL,

    PRIMARY KEY (review_id, idx)
);

-- обязанная сторона пункта: первая роль в именительном падеже («Заказчик уплачивает Исполнителю…» → Заказчик).
-- По смыслу модель не отличает неустойку Заказчика от неустойки Исполнителя: прошлые решения сравниваются только
-- при той же обязанной стороне (или когда сторона не названа)
CREATE FUNCTION pravkiapp.obligor(t text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN substring(coalesce(t, '') FROM
        '(?:^|[^А-Яа-яЁё])(Заказчик|Исполнитель|Поставщик|Покупатель|Арендатор|Арендодатель|Подрядчик)(?![А-Яа-яЁё])');

CREATE FUNCTION pravkiapp.same_obligor(a text, b text) RETURNS boolean
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN pravkiapp.obligor(a) IS NULL OR pravkiapp.obligor(b) IS NULL OR pravkiapp.obligor(a) = pravkiapp.obligor(b);
