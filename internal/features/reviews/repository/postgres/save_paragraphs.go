package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// SaveParagraphs — абзацы нашей редакции разбора с векторами (по одному на абзац).
func (r *ReviewsRepository) SaveParagraphs(ctx context.Context, reviewID int, model string, paras []core_domain.DocParagraph, vectors [][]float32) error {
	if len(paras) == 0 {
		return nil
	}
	if len(vectors) != len(paras) {
		return fmt.Errorf("векторов %d, абзацев %d", len(vectors), len(paras))
	}
	idx, clauses, texts, lits := make([]int32, len(paras)), make([]string, len(paras)), make([]string, len(paras)), make([]string, len(paras))
	for i, p := range paras {
		idx[i], clauses[i], texts[i], lits[i] = int32(p.Index), p.Clause, p.Text, vectorLiteral(vectors[i])
	}
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	_, err := r.pool.Exec(ctx, `
	INSERT INTO pravkiapp.review_paragraphs (review_id, idx, clause, text, model, embedding)
	SELECT $1, i, left(c, 50), t, $2, l::vector FROM unnest($3::int[], $4::text[], $5::text[], $6::text[]) AS x(i, c, t, l)
	ON CONFLICT (review_id, idx) DO UPDATE SET clause = EXCLUDED.clause, text = EXCLUDED.text, model = EXCLUDED.model,
	                                           embedding = EXCLUDED.embedding;`,
		reviewID, model, idx, clauses, texts, lits)
	if err != nil {
		return fmt.Errorf("save paragraphs: %w", err)
	}
	return nil
}
