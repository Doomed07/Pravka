package reviews_service

import (
	"context"
)

// DeleteProject удаляет договор со всеми раундами. Файлы в папке договора остаются на диске.
func (s *ReviewsService) DeleteProject(ctx context.Context, userID, id int) error {
	return s.repo.DeleteProject(ctx, userID, id)
}
