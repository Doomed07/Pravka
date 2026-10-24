package reviews_service

import (
	"context"
	"fmt"
	"strings"
	"unicode/utf8"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	"github.com/Doomed07/Pravka/internal/engine"
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
	return s.engine.Answer(ctx, unified, document, changes, choices, author)
}
