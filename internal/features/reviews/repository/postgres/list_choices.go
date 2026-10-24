package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// ListChoices — решения юриста по правкам разбора. Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ListChoices(ctx context.Context, userID, reviewID int) ([]core_domain.ReviewChoice, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	rows, err := r.pool.Query(ctx, `SELECT change_id, choice, text FROM pravkiapp.review_choices
	WHERE review_id = $1 ORDER BY change_id;`, reviewID)
	if err != nil {
		return nil, fmt.Errorf("select choices: %w", err)
	}
	defer rows.Close()
	out := []core_domain.ReviewChoice{}
	for rows.Next() {
		var m ChoiceModel
		if err := rows.Scan(&m.ChangeID, &m.Choice, &m.Text); err != nil {
			return nil, fmt.Errorf("scan choice: %w", err)
		}
		out = append(out, choiceDomainFromModel(m))
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate choices: %w", err)
	}
	return out, nil
}
