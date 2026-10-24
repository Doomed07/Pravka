package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// Договор с числом раундов и сведениями о последнем разборе (плейбук и роль — для следующего раунда).
const projectSummaryQuery = `
SELECT p.id, p.user_id, p.name, p.created_at,
       (SELECT count(*) FROM pravkiapp.reviews r WHERE r.project_id = p.id),
       coalesce(l.id, 0), coalesce(l.created_at, p.created_at), coalesce(l.playbook, ''), coalesce(l.playbook_name, ''),
       coalesce(l.our_role, ''), coalesce(l.contract_type, '')
FROM pravkiapp.projects p
LEFT JOIN LATERAL (SELECT id, created_at, playbook, playbook_name, our_role, contract_type FROM pravkiapp.reviews r
                   WHERE r.project_id = p.id ORDER BY r.created_at DESC, r.id DESC LIMIT 1) l ON true
WHERE p.user_id = $1`

// ListProjects — договоры пользователя, недавно менявшиеся — первыми.
func (r *ReviewsRepository) ListProjects(ctx context.Context, userID, limit int) ([]core_domain.ProjectSummary, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	rows, err := r.pool.Query(ctx, projectSummaryQuery+` ORDER BY coalesce(l.created_at, p.created_at) DESC, p.id DESC LIMIT $2;`,
		userID, limit)
	if err != nil {
		return nil, fmt.Errorf("select projects: %w", err)
	}
	defer rows.Close()
	out := []core_domain.ProjectSummary{}
	for rows.Next() {
		var m ProjectSummaryModel
		if err := scanProjectSummary(rows, &m); err != nil {
			return nil, fmt.Errorf("scan project: %w", err)
		}
		out = append(out, projectSummaryDomainFromModel(m))
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate projects: %w", err)
	}
	return out, nil
}
