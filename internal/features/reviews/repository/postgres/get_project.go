package reviews_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

func scanProjectSummary(row interface{ Scan(dest ...any) error }, m *ProjectSummaryModel) error {
	return row.Scan(&m.ID, &m.UserID, &m.Name, &m.CreatedAt, &m.Rounds, &m.LastReviewID, &m.LastAt, &m.Playbook,
		&m.PlaybookName, &m.OurRole, &m.ContractType)
}

// GetProject — договор пользователя. Чужой договор неотличим от несуществующего (404).
func (r *ReviewsRepository) GetProject(ctx context.Context, userID, id int) (core_domain.ProjectSummary, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	var m ProjectSummaryModel
	if err := scanProjectSummary(r.pool.QueryRow(ctx, projectSummaryQuery+` AND p.id = $2;`, userID, id), &m); err != nil {
		if errors.Is(err, core_postgres_pool.ErrNoRows) {
			return core_domain.ProjectSummary{}, fmt.Errorf("project %d: %w", id, core_errors.ErrNotFound)
		}
		return core_domain.ProjectSummary{}, fmt.Errorf("select project: %w", err)
	}
	return projectSummaryDomainFromModel(m), nil
}
