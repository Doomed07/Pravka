package reviews_service

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func (s *ReviewsService) List(ctx context.Context, userID, limit, offset int) ([]core_domain.ContractReview, error) {
	if limit <= 0 {
		limit = DefaultLimit
	}
	if limit > MaxLimit+1 { // +1: приём «limit+1» для пагинации на фронтенде
		return nil, fmt.Errorf("limit must be at most %d: %w", MaxLimit+1, core_errors.ErrInvalidArgument)
	}
	if offset < 0 {
		return nil, fmt.Errorf("offset must be non-negative: %w", core_errors.ErrInvalidArgument)
	}
	return s.repo.ListReviews(ctx, userID, limit, offset)
}
