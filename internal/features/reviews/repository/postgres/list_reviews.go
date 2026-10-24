package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

func (r *ReviewsRepository) ListReviews(ctx context.Context, userID, limit, offset int) ([]core_domain.ContractReview, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	rows, err := r.pool.Query(ctx, `SELECT `+columns+` FROM pravkiapp.reviews WHERE user_id = $1
	ORDER BY created_at DESC, id DESC LIMIT $2 OFFSET $3;`, userID, limit, offset)
	if err != nil {
		return nil, fmt.Errorf("select reviews: %w", err)
	}
	defer rows.Close()
	out := []core_domain.ContractReview{}
	for rows.Next() {
		rev, err := scanReview(rows)
		if err != nil {
			return nil, fmt.Errorf("scan review: %w", err)
		}
		out = append(out, rev)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate reviews: %w", err)
	}
	return out, nil
}
