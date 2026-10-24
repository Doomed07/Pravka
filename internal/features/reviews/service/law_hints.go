package reviews_service

import (
	"context"
	"errors"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	"github.com/Doomed07/Pravka/internal/engine"
)

// LawHints — «что говорит ГК» к правкам разбора. Векторы правок считаются при первом обращении (и для разборов,
// сделанных раньше). Модель для векторов не настроена — подсказок нет, это не ошибка: решения от них не зависят.
func (s *ReviewsService) LawHints(ctx context.Context, userID, id int) ([]core_domain.LawHint, error) {
	missing, err := s.repo.ChangesWithoutVectors(ctx, userID, id)
	if err != nil {
		return nil, err
	}
	if err := s.embedChanges(ctx, id, missing); err != nil && !errors.Is(err, engine.ErrNoEmbedModel) {
		return nil, err
	}
	return s.repo.ListLawHints(ctx, userID, id)
}
