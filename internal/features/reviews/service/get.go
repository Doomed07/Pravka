package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

func (s *ReviewsService) Get(ctx context.Context, userID, id int) (core_domain.ContractReview, error) {
	return s.repo.GetReview(ctx, userID, id)
}
