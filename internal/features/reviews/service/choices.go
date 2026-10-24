package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

func (s *ReviewsService) Choices(ctx context.Context, userID, id int) ([]core_domain.ReviewChoice, error) {
	return s.repo.ListChoices(ctx, userID, id)
}
