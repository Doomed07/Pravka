package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// Projects — договоры пользователя (для выбора договора в форме нового разбора).
func (s *ReviewsService) Projects(ctx context.Context, userID int) ([]core_domain.ProjectSummary, error) {
	return s.repo.ListProjects(ctx, userID, MaxLimit)
}
