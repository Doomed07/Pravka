package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func (r *ReviewsRepository) DeleteReview(ctx context.Context, userID, id int) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	tag, err := r.pool.Exec(ctx, `DELETE FROM pravkiapp.reviews WHERE id = $1 AND user_id = $2;`, id, userID)
	if err != nil {
		return fmt.Errorf("delete review: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return fmt.Errorf("review %d: %w", id, core_errors.ErrNotFound)
	}
	return nil
}
