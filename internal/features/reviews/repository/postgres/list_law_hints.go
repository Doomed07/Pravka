package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// ListLawHints — «что говорит ГК» к правкам разбора: до $3 ближайших по смыслу пунктов ГК в частях кодекса для этого
// типа договора (pravkiapp.in_law_scope), не дальше $3; темы из core_domain.NoLawTopics пропускаются.
// Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ListLawHints(ctx context.Context, userID, reviewID int) ([]core_domain.LawHint, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	rows, err := r.pool.Query(ctx, `
	SELECT v.change_id, h.article, h.point, h.title, h.chapter, h.edited, h.text, h.distance
	FROM pravkiapp.reviews r
	JOIN pravkiapp.review_vectors v ON v.review_id = r.id
	JOIN LATERAL jsonb_array_elements(r.changes) c ON c->>'id' = v.change_id
	CROSS JOIN LATERAL (
	    SELECT p.article, p.point, p.title, p.chapter, p.edited, p.text, p.embedding <=> v.embedding AS distance
	    FROM pravkiapp.law_points p
	    WHERE p.code = 'ГК РФ' AND p.embedding IS NOT NULL AND pravkiapp.in_law_scope(r.contract_type, p.article)
	    ORDER BY p.embedding <=> v.embedding
	    LIMIT $2
	) h
	WHERE r.id = $1 AND r.contract_type IN ('supply', 'services') AND h.distance <= $3
	  AND NOT (coalesce(c->>'topic', '') = ANY($4))
	ORDER BY v.change_id, h.distance;`, reviewID, core_domain.MaxLawHints, core_domain.LawHintMaxDistance, core_domain.NoLawTopics)
	if err != nil {
		return nil, fmt.Errorf("select law hints: %w", err)
	}
	defer rows.Close()
	out := []core_domain.LawHint{}
	for rows.Next() {
		var m LawHintModel
		if err := rows.Scan(&m.ChangeID, &m.Article, &m.Point, &m.Title, &m.Chapter, &m.Edited, &m.Text, &m.Distance); err != nil {
			return nil, fmt.Errorf("scan law hint: %w", err)
		}
		out = append(out, lawHintDomainFromModel(m))
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate law hints: %w", err)
	}
	return out, nil
}
