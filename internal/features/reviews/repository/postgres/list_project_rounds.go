package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// ListProjectRounds — раунды договора от первого к последнему: правки и решения юриста по ним. Чужой договор — ErrNotFound.
func (r *ReviewsRepository) ListProjectRounds(ctx context.Context, userID, projectID int) ([]core_domain.ProjectRound, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetProject(ctx, userID, projectID); err != nil {
		return nil, err
	}
	rows, err := r.pool.Query(ctx, `
	SELECT r.id, r.created_at, r.theirs_name, r.base_name, r.changes,
	       coalesce((SELECT jsonb_agg(jsonb_build_object('c', c.change_id, 'k', c.choice, 't', c.text))
	                 FROM pravkiapp.review_choices c WHERE c.review_id = r.id), '[]'::jsonb)
	FROM pravkiapp.reviews r WHERE r.project_id = $1 AND r.user_id = $2 ORDER BY r.created_at, r.id;`, projectID, userID)
	if err != nil {
		return nil, fmt.Errorf("select project rounds: %w", err)
	}
	defer rows.Close()
	out := []core_domain.ProjectRound{}
	for rows.Next() {
		var m ProjectRoundModel
		if err := rows.Scan(&m.ReviewID, &m.CreatedAt, &m.TheirsName, &m.BaseName, &m.Changes, &m.Choices); err != nil {
			return nil, fmt.Errorf("scan project round: %w", err)
		}
		round, err := projectRoundDomainFromModel(m, len(out)+1)
		if err != nil {
			return nil, err
		}
		out = append(out, round)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate project rounds: %w", err)
	}
	return out, nil
}
