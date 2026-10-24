package reviews_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

// GetReview — разбор пользователя. Чужой разбор неотличим от несуществующего (404), чтобы не раскрывать id.
func (r *ReviewsRepository) GetReview(ctx context.Context, userID, id int) (core_domain.ContractReview, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	row := r.pool.QueryRow(ctx, `SELECT `+columns+` FROM pravkiapp.reviews WHERE id = $1 AND user_id = $2;`, id, userID)
	rev, err := scanReview(row)
	if err != nil {
		if errors.Is(err, core_postgres_pool.ErrNoRows) {
			return core_domain.ContractReview{}, fmt.Errorf("review %d: %w", id, core_errors.ErrNotFound)
		}
		return core_domain.ContractReview{}, fmt.Errorf("select review: %w", err)
	}
	return rev, nil
}
