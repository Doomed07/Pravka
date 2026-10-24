package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// Wordings — «ваши прошлые формулировки» к правкам разбора: похожие пункты из нашей редакции в прошлых разборах.
func (s *ReviewsService) Wordings(ctx context.Context, userID, id int) ([]core_domain.Wording, error) {
	if err := s.indexIfNeeded(ctx, userID, id); err != nil {
		return nil, err
	}
	return s.repo.ListWordings(ctx, userID, id)
}
