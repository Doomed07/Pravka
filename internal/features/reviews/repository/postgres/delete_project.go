package reviews_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

// DeleteProject удаляет договор вместе со всеми его раундами (разборами, решениями, векторами). Контрагент остаётся.
// Чужой или несуществующий договор — ErrNotFound. Файлы на диске не удаляются: сайт папки не трогает.
func (r *ReviewsRepository) DeleteProject(ctx context.Context, userID, id int) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	var deleted int
	err := r.pool.QueryRow(ctx, `DELETE FROM pravkiapp.projects WHERE id = $1 AND user_id = $2 RETURNING id;`,
		id, userID).Scan(&deleted)
	if err != nil {
		if errors.Is(err, core_postgres_pool.ErrNoRows) {
			return fmt.Errorf("project %d: %w", id, core_errors.ErrNotFound)
		}
		return fmt.Errorf("delete project: %w", err)
	}
	return nil
}
