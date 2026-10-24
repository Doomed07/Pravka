package reviews_repository_postgres

import (
	"context"
	"fmt"
)

// MarkIndexed — векторы абзацев и правок разбора посчитаны.
func (r *ReviewsRepository) MarkIndexed(ctx context.Context, reviewID int) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.pool.Exec(ctx, `UPDATE pravkiapp.reviews SET indexed_at = NOW() WHERE id = $1;`, reviewID); err != nil {
		return fmt.Errorf("mark indexed: %w", err)
	}
	return nil
}
