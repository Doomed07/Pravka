package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// Precedents — «как решали раньше»: прошлые решения юриста по похожим правкам. Только подсказка. Сначала по словам;
// к правкам, для которых по словам ничего нет, — по смыслу (если векторы посчитаны).
func (s *ReviewsService) Precedents(ctx context.Context, userID, id int) ([]core_domain.Precedent, error) {
	words, err := s.repo.ListPrecedents(ctx, userID, id)
	if err != nil {
		return nil, err
	}
	if err := s.indexIfNeeded(ctx, userID, id); err != nil {
		return nil, err
	}
	found := make([]string, 0, len(words))
	for _, p := range words {
		found = append(found, p.ChangeID)
	}
	sense, err := s.repo.ListSemanticPrecedents(ctx, userID, id, found)
	if err != nil {
		return nil, err
	}
	return append(words, sense...), nil
}
