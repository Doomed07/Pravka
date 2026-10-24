package reviews_repository_postgres

import (
	"context"
	"fmt"
)

// ReviewsToIndex — разборы поставки и услуг, у которых ещё нет векторов (старые сначала). Для фоновой индексации.
func (r *ReviewsRepository) ReviewsToIndex(ctx context.Context, limit int) ([]int, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	rows, err := r.pool.Query(ctx, `SELECT id FROM pravkiapp.reviews
	WHERE indexed_at IS NULL AND contract_type IN ('supply', 'services') ORDER BY created_at, id LIMIT $1;`, limit)
	if err != nil {
		return nil, fmt.Errorf("select reviews to index: %w", err)
	}
	defer rows.Close()
	out := []int{}
	for rows.Next() {
		var id int
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("scan review id: %w", err)
		}
		out = append(out, id)
	}
	return out, rows.Err()
}
