package reviews_service

import (
	"context"
	"errors"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"github.com/Doomed07/Pravka/internal/engine"
	"go.uber.org/zap"
)

// indexIfNeeded — разбор открыли раньше, чем до него дошла фоновая индексация: считаем векторы сейчас.
func (s *ReviewsService) indexIfNeeded(ctx context.Context, userID, id int) error {
	need, err := s.repo.NeedsIndex(ctx, userID, id)
	if err != nil || !need {
		return err
	}
	if err := s.IndexReview(ctx, id); err != nil && !errors.Is(err, engine.ErrNoEmbedModel) {
		return err
	}
	return nil
}

// IndexReview считает векторы абзацев нашей редакции и правок разбора. Модели для векторов нет —
// engine.ErrNoEmbedModel, разбор остаётся непроиндексированным (дойдём позже).
func (s *ReviewsService) IndexReview(ctx context.Context, id int) error {
	document, changes, err := s.repo.IndexSource(ctx, id)
	if err != nil {
		return err
	}
	paras, err := core_domain.OurParagraphs(document)
	if err != nil {
		return err
	}
	for i := 0; i < len(paras); i += embedBatch {
		batch := paras[i:min(i+embedBatch, len(paras))]
		texts := make([]string, len(batch))
		for j, p := range batch {
			texts[j] = p.Text
		}
		model, vectors, err := s.engine.Embed(ctx, texts)
		if err != nil {
			return err
		}
		if err := s.repo.SaveParagraphs(ctx, id, model, batch, vectors); err != nil {
			return err
		}
	}
	if err := s.embedChanges(ctx, id, changes); err != nil {
		return err
	}
	return s.repo.MarkIndexed(ctx, id)
}

// embedChanges — векторы правок (для «Что говорит ГК» и «как решали раньше» по смыслу).
func (s *ReviewsService) embedChanges(ctx context.Context, id int, changes []core_domain.VectorChange) error {
	for i := 0; i < len(changes); i += embedBatch {
		batch := changes[i:min(i+embedBatch, len(changes))]
		texts := make([]string, len(batch))
		for j, c := range batch {
			texts[j] = c.EmbedText()
		}
		model, vectors, err := s.engine.Embed(ctx, texts)
		if err != nil {
			return err
		}
		byID := make(map[string][]float32, len(batch))
		for j, c := range batch {
			byID[c.ID] = vectors[j]
		}
		if err := s.repo.SaveVectors(ctx, id, model, byID); err != nil {
			return err
		}
	}
	return nil
}

// RunIndexer — фоновая индексация разборов поставки и услуг: при запуске, после каждого нового разбора и раз в минуту.
// Ошибки только в журнал: сайт работает и без векторов.
func (s *ReviewsService) RunIndexer(ctx context.Context, log *core_logger.Logger) {
	for {
		ids, err := s.repo.ReviewsToIndex(ctx, 5)
		if err != nil {
			log.Warn("index: list reviews", zap.Error(err))
		}
		for _, id := range ids {
			if err := s.IndexReview(ctx, id); err != nil {
				if !errors.Is(err, engine.ErrNoEmbedModel) {
					log.Warn("index review failed", zap.Int("review", id), zap.Error(err))
				}
				break // модели нет или движок недоступен — попробуем позже
			}
		}
		if len(ids) == 5 && err == nil {
			continue // ещё есть очередь
		}
		select {
		case <-ctx.Done():
			return
		case <-s.nudge:
		case <-time.After(time.Minute):
		}
	}
}
