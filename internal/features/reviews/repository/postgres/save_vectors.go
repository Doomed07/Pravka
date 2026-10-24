package reviews_repository_postgres

import (
	"context"
	"fmt"
)

// SaveVectors — векторы правок разбора (по номеру правки), посчитанные моделью model.
func (r *ReviewsRepository) SaveVectors(ctx context.Context, reviewID int, model string, vectors map[string][]float32) error {
	if len(vectors) == 0 {
		return nil
	}
	ids, lits := make([]string, 0, len(vectors)), make([]string, 0, len(vectors))
	for id, v := range vectors {
		ids, lits = append(ids, id), append(lits, vectorLiteral(v))
	}
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	_, err := r.pool.Exec(ctx, `
	INSERT INTO pravkiapp.review_vectors (review_id, change_id, model, embedding)
	SELECT $1, id, $2, lit::vector FROM unnest($3::text[], $4::text[]) AS x(id, lit)
	ON CONFLICT (review_id, change_id) DO UPDATE SET model = EXCLUDED.model, embedding = EXCLUDED.embedding;`,
		reviewID, model, ids, lits)
	if err != nil {
		return fmt.Errorf("save vectors: %w", err)
	}
	return nil
}
