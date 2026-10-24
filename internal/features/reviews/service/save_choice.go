package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

func (s *ReviewsService) SaveChoice(ctx context.Context, userID, id int, c core_domain.ReviewChoice) error {
	if err := c.Validate(); err != nil {
		return err
	}
	return s.repo.SaveChoice(ctx, userID, id, c)
}
