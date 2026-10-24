package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// Summary — сводка раунда по темам: собирается из сохранённого списка правок при каждом запросе (работает и для
// разборов, сделанных до неё).
func (s *ReviewsService) Summary(ctx context.Context, userID, id int) (core_domain.RoundSummary, error) {
	changes, err := s.repo.GetFile(ctx, userID, id, "changes")
	if err != nil {
		return core_domain.RoundSummary{}, err
	}
	return core_domain.SummarizeRound(changes)
}
