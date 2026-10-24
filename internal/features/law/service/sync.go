package law_service

import (
	"context"
	"errors"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	"github.com/Doomed07/Pravka/internal/engine"
)

// Sync загружает нормы, если в базе другая версия или нет векторов. Возвращает true, если векторы есть.
func (s *LawService) Sync(ctx context.Context) (bool, error) {
	first, err := s.engine.Law(ctx, 0, pageSize)
	if err != nil {
		return false, err
	}
	version, model, err := s.repo.Meta(ctx, Code)
	if err != nil {
		return false, err
	}
	if version == first.Version && model != "" {
		return true, nil
	}
	if err := s.repo.Clear(ctx, Code); err != nil {
		return false, err
	}
	model, withVectors := "", true
	for page, offset := first, 0; ; {
		if page.Version != first.Version {
			return false, fmt.Errorf("нормы в движке изменились во время загрузки")
		}
		for i := 0; i < len(page.Points); i += embedSize {
			batch := page.Points[i:min(i+embedSize, len(page.Points))]
			var vectors [][]float32
			if withVectors {
				texts := make([]string, len(batch))
				for j, p := range batch {
					texts[j] = embedText(p)
				}
				m, v, err := s.engine.Embed(ctx, texts)
				switch {
				case errors.Is(err, engine.ErrNoEmbedModel):
					withVectors = false // без модели — только поиск по словам; векторы досчитаются при следующей проверке
				case err != nil:
					return false, err
				default:
					model, vectors = m, v
				}
			}
			if err := s.repo.Insert(ctx, batch, vectors); err != nil {
				return false, err
			}
		}
		offset += len(page.Points)
		if offset >= first.Total || len(page.Points) == 0 {
			break
		}
		if page, err = s.engine.Law(ctx, offset, pageSize); err != nil {
			return false, err
		}
	}
	if !withVectors {
		model = ""
	}
	if err := s.repo.SetMeta(ctx, Code, first.Version, model); err != nil {
		return false, err
	}
	return withVectors, nil
}

// embedText — что видит модель векторов: название статьи и текст пункта.
func embedText(p core_domain.LawPoint) string {
	t := []rune(p.Title + ". " + p.Text)
	if len(t) > maxText {
		t = t[:maxText]
	}
	return string(t)
}
