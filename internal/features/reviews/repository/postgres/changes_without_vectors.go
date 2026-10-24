package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// ChangesWithoutVectors — правки разбора без посчитанного вектора (для «Что говорит ГК» и «как решали раньше» по
// смыслу). Только поставка и услуги; комментарии и технические правки (опечатки, пунктуация) пропускаются.
// Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ChangesWithoutVectors(ctx context.Context, userID, reviewID int) ([]core_domain.VectorChange, error) {
	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	return r.changesWithoutVectors(ctx, reviewID)
}

func (r *ReviewsRepository) changesWithoutVectors(ctx context.Context, reviewID int) ([]core_domain.VectorChange, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	rows, err := r.pool.Query(ctx, `
	SELECT c->>'id', coalesce(c->>'kind', ''), coalesce(c->>'topic', ''), coalesce(c->>'context', ''),
	       coalesce(c->>'context_after', '')
	FROM pravkiapp.reviews r CROSS JOIN LATERAL jsonb_array_elements(r.changes) c
	WHERE r.id = $1 AND r.contract_type IN ('supply', 'services') AND coalesce(c->>'kind', '') <> 'comment'
	  AND coalesce(c->>'materiality', '') <> 'техническая'
	  AND NOT EXISTS (SELECT 1 FROM pravkiapp.review_vectors v WHERE v.review_id = r.id AND v.change_id = c->>'id');`,
		reviewID)
	if err != nil {
		return nil, fmt.Errorf("select changes without vectors: %w", err)
	}
	defer rows.Close()
	out := []core_domain.VectorChange{}
	for rows.Next() {
		var m VectorChangeModel
		if err := rows.Scan(&m.ID, &m.Kind, &m.Topic, &m.Context, &m.ContextAfter); err != nil {
			return nil, fmt.Errorf("scan change: %w", err)
		}
		out = append(out, vectorChangeDomainFromModel(m))
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate changes: %w", err)
	}
	return out, nil
}
