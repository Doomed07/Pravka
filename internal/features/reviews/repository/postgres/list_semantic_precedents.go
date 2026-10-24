package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// ListSemanticPrecedents — «как решали раньше» по смыслу: к правкам разбора, кроме skip (у них уже есть подсказки
// по словам), — прошлые решения юриста по правкам, близким по вектору (не дальше core_domain.SemanticPrecedentMaxDistance),
// того же типа договора, роли, темы и обязанной стороны (как и в поиске по словам).
// Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ListSemanticPrecedents(ctx context.Context, userID, reviewID int, skip []string) ([]core_domain.Precedent, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	if skip == nil {
		skip = []string{}
	}
	rows, err := r.pool.Query(ctx, `
	WITH cur AS (
	    SELECT id, contract_type, our_role, changes FROM pravkiapp.reviews
	    WHERE id = $1 AND user_id = $2 AND contract_type IN ('supply', 'services')
	), mine AS (
	    SELECT v.change_id, v.embedding, coalesce(c->>'topic', '') AS topic,
	           coalesce(nullif(c->>'context_after', ''), c->>'context') AS para
	    FROM cur JOIN pravkiapp.review_vectors v ON v.review_id = cur.id
	    JOIN LATERAL jsonb_array_elements(cur.changes) c ON c->>'id' = v.change_id
	    WHERE NOT (v.change_id = ANY($3))
	), found AS (
	    SELECT mine.change_id, s.*, row_number() OVER (PARTITION BY mine.change_id ORDER BY s.distance, s.created_at DESC) AS n
	    FROM mine CROSS JOIN cur CROSS JOIN LATERAL (
	        SELECT p.id AS review_id, rc.change_id AS past_change, p.theirs_name, p.created_at, rc.choice, rc.text,
	               coalesce(c->>'clause', '') AS clause, coalesce(c->>'topic', '') AS topic,
	               coalesce(c->>'before', '') AS before, coalesce(c->>'after', '') AS after,
	               pv.embedding <=> mine.embedding AS distance
	        FROM pravkiapp.reviews p
	        JOIN pravkiapp.review_choices rc ON rc.review_id = p.id AND rc.choice IN ('accept', 'reject', 'counter')
	        JOIN pravkiapp.review_vectors pv ON pv.review_id = p.id AND pv.change_id = rc.change_id
	        JOIN LATERAL jsonb_array_elements(p.changes) c ON c->>'id' = rc.change_id
	        WHERE p.user_id = $2 AND p.id <> cur.id AND p.contract_type = cur.contract_type AND p.our_role = cur.our_role
	          AND (coalesce(c->>'topic', '') = mine.topic OR mine.topic IN ('', 'прочее')
	               OR coalesce(c->>'topic', '') IN ('', 'прочее'))
	          AND pravkiapp.same_obligor(mine.para, coalesce(nullif(c->>'context_after', ''), c->>'context'))
	        ORDER BY distance LIMIT $5
	    ) s
	    WHERE s.distance <= $4
	)
	SELECT change_id, review_id, past_change, theirs_name, created_at, clause, topic, before, after, choice, text, distance
	FROM found WHERE n <= $5 ORDER BY change_id, n;`,
		reviewID, userID, skip, core_domain.SemanticPrecedentMaxDistance, core_domain.MaxPrecedents)
	if err != nil {
		return nil, fmt.Errorf("select semantic precedents: %w", err)
	}
	defer rows.Close()
	out := []core_domain.Precedent{}
	for rows.Next() {
		var m PrecedentModel
		if err := rows.Scan(&m.ChangeID, &m.ReviewID, &m.PastChangeID, &m.TheirsName, &m.CreatedAt, &m.Clause, &m.Topic,
			&m.Before, &m.After, &m.Choice, &m.Text, &m.Distance); err != nil {
			return nil, fmt.Errorf("scan semantic precedent: %w", err)
		}
		out = append(out, precedentDomainFromModel(m, true))
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate semantic precedents: %w", err)
	}
	return out, nil
}
