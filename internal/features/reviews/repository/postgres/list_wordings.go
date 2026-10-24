package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// ListWordings — к правке разбора: абзацы нашей редакции из других разборов того же юриста, типа договора и роли,
// ближайшие по смыслу к нашему абзацу с этой правкой (не дальше core_domain.WordingMaxDistance). Тот же текст
// (тот же шаблон) и пункт с другой обязанной стороной (неустойка Покупателя к неустойке Поставщика) не показываются;
// одинаковые тексты из разных разборов — один раз. Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ListWordings(ctx context.Context, userID, reviewID int) ([]core_domain.Wording, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	rows, err := r.pool.Query(ctx, `
	WITH cur AS (
	    SELECT id, contract_type, our_role, changes FROM pravkiapp.reviews
	    WHERE id = $1 AND user_id = $2 AND contract_type IN ('supply', 'services')
	), mine AS (
	    SELECT c->>'id' AS change_id, p.text, p.embedding
	    FROM cur CROSS JOIN LATERAL jsonb_array_elements(cur.changes) c
	    JOIN pravkiapp.review_paragraphs p ON p.review_id = cur.id AND p.idx = (c->>'paragraph_index')::int
	    WHERE coalesce(c->>'kind', '') <> 'comment' AND coalesce(c->>'materiality', '') <> 'техническая'
	      AND coalesce(c->>'topic', '') <> 'стороны и реквизиты'
	), found AS (
	    SELECT mine.change_id, w.*, row_number() OVER (PARTITION BY mine.change_id, w.norm ORDER BY w.distance) AS dup
	    FROM mine CROSS JOIN cur CROSS JOIN LATERAL (
	        SELECT p.review_id, r.theirs_name, r.created_at, p.clause, p.text, p.embedding <=> mine.embedding AS distance,
	               regexp_replace(lower(p.text), '\s+', ' ', 'g') AS norm
	        FROM pravkiapp.review_paragraphs p JOIN pravkiapp.reviews r ON r.id = p.review_id
	        WHERE r.user_id = $2 AND r.id <> cur.id AND r.contract_type = cur.contract_type AND r.our_role = cur.our_role
	          AND regexp_replace(lower(p.text), '\s+', ' ', 'g') <> regexp_replace(lower(mine.text), '\s+', ' ', 'g')
	          AND pravkiapp.same_obligor(p.text, mine.text)
	        ORDER BY distance LIMIT 20
	    ) w
	    WHERE w.distance <= $3
	), ranked AS (
	    SELECT *, row_number() OVER (PARTITION BY change_id ORDER BY distance, created_at DESC) AS n FROM found WHERE dup = 1
	)
	SELECT change_id, review_id, theirs_name, created_at, clause, text, distance FROM ranked WHERE n <= $4
	ORDER BY change_id, n;`, reviewID, userID, core_domain.WordingMaxDistance, core_domain.MaxWordings)
	if err != nil {
		return nil, fmt.Errorf("select wordings: %w", err)
	}
	defer rows.Close()
	out := []core_domain.Wording{}
	for rows.Next() {
		var m WordingModel
		if err := rows.Scan(&m.ChangeID, &m.ReviewID, &m.TheirsName, &m.CreatedAt, &m.Clause, &m.Text, &m.Distance); err != nil {
			return nil, fmt.Errorf("scan wording: %w", err)
		}
		out = append(out, wordingDomainFromModel(m))
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate wordings: %w", err)
	}
	return out, nil
}
