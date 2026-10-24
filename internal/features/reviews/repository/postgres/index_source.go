package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// IndexSource — что индексировать в разборе: единая версия (JSON) и правки без векторов. Без проверки владельца:
// только для фоновой индексации и после NeedsIndex.
func (r *ReviewsRepository) IndexSource(ctx context.Context, reviewID int) ([]byte, []core_domain.VectorChange, error) {
	c, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	var document []byte
	err := r.pool.QueryRow(c, `SELECT convert_to(document::text, 'UTF8') FROM pravkiapp.reviews WHERE id = $1;`, reviewID).Scan(&document)
	if err != nil {
		return nil, nil, fmt.Errorf("select document: %w", err)
	}
	changes, err := r.changesWithoutVectors(ctx, reviewID)
	return document, changes, err
}
