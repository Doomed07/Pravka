package law_service

import (
	"context"
	"errors"
	"fmt"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"github.com/Doomed07/Pravka/internal/engine"
	"go.uber.org/zap"
)

// Code — какой закон загружается. Пока один: ГК РФ.
const Code = "ГК РФ"

const (
	pageSize  = 500 // пунктов за один запрос к движку
	embedSize = 64  // текстов за один запрос векторов (предел движка)
	maxText   = 2000
)

type Repository interface {
	Meta(ctx context.Context, code string) (version, model string, err error)
	Clear(ctx context.Context, code string) error
	Insert(ctx context.Context, points []core_domain.LawPoint, vectors [][]float32) error
	SetMeta(ctx context.Context, code, version, model string) error
}

type Engine interface {
	Law(ctx context.Context, offset, limit int) (engine.LawPage, error)
	Embed(ctx context.Context, texts []string) (string, [][]float32, error)
}

// LawService держит нормы в базе в соответствии с движком: загружает при новой версии текста и досчитывает векторы,
// если раньше модель для них была недоступна.
type LawService struct {
	repo   Repository
	engine Engine
}

func NewLawService(repo Repository, eng Engine) *LawService {
	return &LawService{repo: repo, engine: eng}
}

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

// Run — при запуске сервиса и затем раз в час, пока нормы не загружены с векторами (движок или модель могли
// ещё не подняться). Ошибки только в журнал: сайт работает и без норм.
func (s *LawService) Run(ctx context.Context, log *core_logger.Logger) {
	for {
		start := time.Now()
		done, err := s.Sync(ctx)
		switch {
		case err != nil:
			log.Warn("law sync failed", zap.Error(err))
		case done:
			log.Info("law ready", zap.String("code", Code), zap.Duration("took", time.Since(start)))
			return
		default:
			log.Warn("law loaded without vectors: embedding model unavailable", zap.String("code", Code))
		}
		wait := time.Hour
		if err != nil {
			wait = time.Minute
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
	}
}
