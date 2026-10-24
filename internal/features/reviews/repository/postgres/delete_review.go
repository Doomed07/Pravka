package reviews_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

// DeleteReview удаляет разбор; если это был последний раунд договора, удаляется и сам договор (проект).
func (r *ReviewsRepository) DeleteReview(ctx context.Context, userID, id int) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	var projectID int
	err := r.pool.QueryRow(ctx, `DELETE FROM pravkiapp.reviews WHERE id = $1 AND user_id = $2 RETURNING project_id;`,
		id, userID).Scan(&projectID)
	if err != nil {
		if errors.Is(err, core_postgres_pool.ErrNoRows) {
			return fmt.Errorf("review %d: %w", id, core_errors.ErrNotFound)
		}
		return fmt.Errorf("delete review: %w", err)
	}
	if _, err := r.pool.Exec(ctx, `DELETE FROM pravkiapp.projects p WHERE p.id = $1
	AND NOT EXISTS (SELECT 1 FROM pravkiapp.reviews r WHERE r.project_id = p.id);`, projectID); err != nil {
		return fmt.Errorf("delete empty project: %w", err)
	}
	return nil
}
