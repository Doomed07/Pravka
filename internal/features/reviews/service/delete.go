package reviews_service

import (
	"context"
)

func (s *ReviewsService) Delete(ctx context.Context, userID, id int) error {
	return s.repo.DeleteReview(ctx, userID, id)
}
