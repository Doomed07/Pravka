package reviews_service

import (
	"context"
)

func (s *ReviewsService) File(ctx context.Context, userID, id int, kind string) ([]byte, error) {
	return s.repo.GetFile(ctx, userID, id, kind)
}
