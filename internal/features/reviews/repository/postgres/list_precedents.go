package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// Похожесть прошлой правки на текущую: слова абзаца нашей редакции (вес 0,5) и суть правки — какие слова убраны
// и какие добавлены (вес 0,5). Правки с разными темами не сравниваются: «30% → 10%» в авансе и «30 → 10 дней» в сроке
// поставки дают одну и ту же суть {+10, -30}. Не сравниваются и правки с разной обязанной стороной (неустойка
// Заказчика ≠ неустойка Исполнителя, pravkiapp.same_obligor). «Та же правка» — та же суть в похожем абзаце (не меньше
// половины общих слов); её показываем первой. Остальные — если похожесть не ниже 0,35 при той же теме или не ниже 0,5, когда тема
// у одной из правок не определена. Пороги подобраны на учебных договорах (поставка и услуги); проверка —
// TestReviewsRepository_Precedents.
const precedentsQuery = `
WITH cur AS (
    SELECT contract_type, our_role FROM pravkiapp.reviews
    WHERE id = $1 AND user_id = $2 AND contract_type IN ('supply', 'services')
), mine AS (
    SELECT c->>'id' AS id, coalesce(c->>'topic', '') AS topic,
           lower(btrim(coalesce(c->>'before', ''))) AS b, lower(btrim(coalesce(c->>'after', ''))) AS a,
           pravkiapp.lexemes(c->>'context') AS ctx, pravkiapp.edit_sig(c->>'before', c->>'after') AS sig,
           coalesce(nullif(c->>'context_after', ''), c->>'context') AS para
    FROM pravkiapp.reviews r CROSS JOIN LATERAL jsonb_array_elements(r.changes) c
    WHERE r.id = $1 AND r.user_id = $2 AND coalesce(c->>'kind', '') <> 'comment'
), past AS (
    SELECT p.id AS review_id, rc.change_id AS past_change, p.theirs_name, p.created_at, rc.choice, rc.text,
           coalesce(c->>'clause', '') AS clause, coalesce(c->>'topic', '') AS topic,
           coalesce(c->>'before', '') AS before, coalesce(c->>'after', '') AS after,
           pravkiapp.lexemes(c->>'context') AS ctx, pravkiapp.edit_sig(c->>'before', c->>'after') AS sig,
           coalesce(nullif(c->>'context_after', ''), c->>'context') AS para
    FROM cur
    JOIN pravkiapp.reviews p ON p.user_id = $2 AND p.id <> $1 AND p.contract_type = cur.contract_type
                             AND p.our_role = cur.our_role
    JOIN pravkiapp.review_choices rc ON rc.review_id = p.id AND rc.choice IN ('accept', 'reject', 'counter')
    CROSS JOIN LATERAL jsonb_array_elements(p.changes) c
    WHERE c->>'id' = rc.change_id
), pairs AS (
    SELECT mine.id AS change_id, past.*, mine.topic = past.topic AND past.topic NOT IN ('', 'прочее') AS same_topic,
           pravkiapp.overlap(mine.ctx, past.ctx) AS ctx_score,
           (cardinality(mine.sig) > 0 AND mine.sig = past.sig)
             OR (lower(btrim(past.before)) = mine.b AND lower(btrim(past.after)) = mine.a) AS same_edit,
           0.5 * pravkiapp.overlap(mine.ctx, past.ctx) + 0.5 * pravkiapp.overlap(mine.sig, past.sig) AS score
    FROM mine CROSS JOIN past
    WHERE (mine.topic = past.topic OR mine.topic IN ('', 'прочее') OR past.topic IN ('', 'прочее'))
      AND pravkiapp.same_obligor(mine.para, past.para)
), scored AS (
    SELECT *, same_edit AND ctx_score >= 0.5 AS same FROM pairs
), ranked AS (
    SELECT *, row_number() OVER (PARTITION BY change_id ORDER BY same DESC, score DESC, created_at DESC) AS n
    FROM scored
    WHERE same OR (same_topic AND score >= 0.35) OR score >= 0.5
)
SELECT change_id, review_id, past_change, theirs_name, created_at, clause, topic, before, after, choice, text, same, score
FROM ranked WHERE n <= $3 ORDER BY change_id, n;`

// ListPrecedents — «как решали раньше» для правок разбора. Чужой разбор — ErrNotFound. Для договоров других типов
// (не поставка и не услуги) подсказок нет: пустой список.
func (r *ReviewsRepository) ListPrecedents(ctx context.Context, userID, reviewID int) ([]core_domain.Precedent, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	rows, err := r.pool.Query(ctx, precedentsQuery, reviewID, userID, core_domain.MaxPrecedents)
	if err != nil {
		return nil, fmt.Errorf("select precedents: %w", err)
	}
	defer rows.Close()
	out := []core_domain.Precedent{}
	for rows.Next() {
		var m PrecedentModel
		if err := rows.Scan(&m.ChangeID, &m.ReviewID, &m.PastChangeID, &m.TheirsName, &m.CreatedAt, &m.Clause, &m.Topic, &m.Before,
			&m.After, &m.Choice, &m.Text, &m.Same, &m.Score); err != nil {
			return nil, fmt.Errorf("scan precedent: %w", err)
		}
		out = append(out, precedentDomainFromModel(m, false))
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate precedents: %w", err)
	}
	return out, nil
}
