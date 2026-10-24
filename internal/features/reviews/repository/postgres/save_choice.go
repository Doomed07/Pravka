package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// SaveChoice — записать решение по правке; пустое решение удаляет запись. Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) SaveChoice(ctx context.Context, userID, reviewID int, c core_domain.ReviewChoice) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return err
	}
	if c.Choice == "" {
		if _, err := r.pool.Exec(ctx, `DELETE FROM pravkiapp.review_choices WHERE review_id = $1 AND change_id = $2;`,
			reviewID, c.ChangeID); err != nil {
			return fmt.Errorf("delete choice: %w", err)
		}
		return nil
	}
	_, err := r.pool.Exec(ctx, `
	INSERT INTO pravkiapp.review_choices (review_id, change_id, choice, text) VALUES ($1, $2, $3, $4)
	ON CONFLICT (review_id, change_id) DO UPDATE SET choice = EXCLUDED.choice, text = EXCLUDED.text, updated_at = NOW();`,
		reviewID, c.ChangeID, c.Choice, c.Text)
	if err != nil {
		return fmt.Errorf("save choice: %w", err)
	}
	return nil
}
