package law_service

import (
	"context"
	"time"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"go.uber.org/zap"
)

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
