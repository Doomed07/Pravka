package law_repository_postgres

import (
	"context"
	"encoding/json"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// Insert добавляет пункты одним запросом; vectors — по одному на пункт или nil (без векторов).
func (r *LawRepository) Insert(ctx context.Context, points []core_domain.LawPoint, vectors [][]float32) error {
	if len(points) == 0 {
		return nil
	}
	if vectors != nil && len(vectors) != len(points) {
		return fmt.Errorf("векторов %d, пунктов %d", len(vectors), len(points))
	}
	rows := make([]LawPointModel, len(points))
	for i, p := range points {
		var v []float32
		if vectors != nil {
			v = vectors[i]
		}
		rows[i] = lawPointModelFromDomain(p, v)
	}
	data, err := json.Marshal(rows)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	_, err = r.pool.Exec(ctx, `
	INSERT INTO pravkiapp.law_points (code, article, seq, point, title, section, chapter, paragraph, edited, text, embedding)
	SELECT code, article, seq, point, title, section, chapter, paragraph, edited, text, embedding::vector
	FROM jsonb_to_recordset($1::jsonb) AS x(code text, article text, seq int, point text, title text, section text,
	                                        chapter text, paragraph text, edited text, text text, embedding text);`, string(data))
	if err != nil {
		return fmt.Errorf("insert law points: %w", err)
	}
	return nil
}
