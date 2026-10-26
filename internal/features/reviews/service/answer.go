package reviews_service

import (
	"context"
	"fmt"
	"strings"
	"unicode/utf8"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"github.com/Doomed07/Pravka/internal/engine"
	"github.com/Doomed07/Pravka/internal/features/reviews/filestore"
	"go.uber.org/zap"
)

// MaxAuthor — предел имени автора наших правок в ответе.
const MaxAuthor = 100

// Answer собирает ответ контрагенту по решениям юриста. Ответ не сохраняется: юрист скачивает его сразу.
// Разбор, сделанный до появления единой версии, ответа не даёт (ErrNotFound): нет файла, к которому применять решения.
func (s *ReviewsService) Answer(ctx context.Context, userID, id int, author string) (engine.AnswerResult, error) {
	author = strings.TrimSpace(author)
	if utf8.RuneCountInString(author) > MaxAuthor {
		return engine.AnswerResult{}, fmt.Errorf("имя автора длиннее %d символов: %w", MaxAuthor, core_errors.ErrInvalidArgument)
	}
	unified, err := s.repo.GetFile(ctx, userID, id, "docx")
	if err != nil {
		return engine.AnswerResult{}, err
	}
	document, err := s.repo.GetFile(ctx, userID, id, "document")
	if err != nil {
		return engine.AnswerResult{}, err
	}
	changes, err := s.repo.GetFile(ctx, userID, id, "changes")
	if err != nil {
		return engine.AnswerResult{}, err
	}
	choices, err := s.repo.ListChoices(ctx, userID, id)
	if err != nil {
		return engine.AnswerResult{}, err
	}
	res, err := s.engine.Answer(ctx, unified, document, changes, choices, author)
	if err != nil {
		return res, err
	}
	s.saveAnswer(ctx, userID, id, res.DOCX)
	return res, nil
}

// saveAnswer кладёт собранный ответ в папку раунда (перезаписывая прошлый). Сбой только в журнал: юрист скачивает файл сразу.
func (s *ReviewsService) saveAnswer(ctx context.Context, userID, id int, data []byte) {
	if !s.files.Enabled() {
		return
	}
	rev, err := s.repo.GetReview(ctx, userID, id)
	if err == nil {
		var project core_domain.ProjectSummary
		if project, err = s.repo.GetProject(ctx, userID, rev.ProjectID); err == nil {
			err = s.files.Save(project.Dir, rev.Round, filestore.AnswerFile+".docx", data)
		}
	}
	if err != nil {
		core_logger.FromCtx(ctx).Warn("answer: file not saved to disk", zap.Error(err))
	}
}
