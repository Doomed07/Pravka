package reviews_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

// NeedsIndex — разбор пользователя ещё не проиндексирован (и это поставка или услуги). Чужой — ErrNotFound.
func (r *ReviewsRepository) NeedsIndex(ctx context.Context, userID, reviewID int) (bool, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	var need bool
	err := r.pool.QueryRow(ctx, `SELECT indexed_at IS NULL AND contract_type IN ('supply', 'services')
	FROM pravkiapp.reviews WHERE id = $1 AND user_id = $2;`, reviewID, userID).Scan(&need)
	if errors.Is(err, core_postgres_pool.ErrNoRows) {
		return false, fmt.Errorf("review %d: %w", reviewID, core_errors.ErrNotFound)
	}
	if err != nil {
		return false, fmt.Errorf("select index state: %w", err)
	}
	return need, nil
}
