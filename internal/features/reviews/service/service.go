package reviews_service

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
	"github.com/Doomed07/Pravka/internal/engine"
)

const (
	DefaultLimit = 20
	MaxLimit     = 100
)

type ReviewsRepository interface {
	CreateReview(ctx context.Context, rev core_domain.ContractReview, files core_domain.ReviewFiles) (core_domain.ContractReview, error)
	ListReviews(ctx context.Context, userID, limit, offset int) ([]core_domain.ContractReview, error)
	GetReview(ctx context.Context, userID, id int) (core_domain.ContractReview, error)
	GetFile(ctx context.Context, userID, id int, kind string) ([]byte, error)
	DeleteReview(ctx context.Context, userID, id int) error
	ListChoices(ctx context.Context, userID, reviewID int) ([]core_domain.ReviewChoice, error)
	SaveChoice(ctx context.Context, userID, reviewID int, c core_domain.ReviewChoice) error
}

type Engine interface {
	Playbooks(ctx context.Context) ([]core_domain.Playbook, error)
	Review(ctx context.Context, r core_domain.ReviewRequest) (engine.Result, []byte, error)
	Answer(ctx context.Context, unified, document, changes []byte, choices []core_domain.ReviewChoice, author string) (engine.AnswerResult, error)
}

type ReviewsService struct {
	repo   ReviewsRepository
	engine Engine
}

func NewReviewsService(repo ReviewsRepository, eng Engine) *ReviewsService {
	return &ReviewsService{repo: repo, engine: eng}
}

func (s *ReviewsService) Playbooks(ctx context.Context) ([]core_domain.Playbook, error) {
	return s.engine.Playbooks(ctx)
}

// Create отправляет договор движку и сохраняет результат. Исходные docx не сохраняются: в базе остаются только отчёты.
func (s *ReviewsService) Create(ctx context.Context, userID int, req core_domain.ReviewRequest) (core_domain.ContractReview, error) {
	req.Theirs.Name = core_domain.CleanFileName(req.Theirs.Name)
	if req.Base != nil {
		req.Base.Name = core_domain.CleanFileName(req.Base.Name)
	}
	if err := req.Validate(); err != nil {
		core_metrics.ReviewsFailed.WithLabelValues("invalid").Inc()
		return core_domain.ContractReview{}, err
	}
	start := time.Now()
	res, xlsx, err := s.engine.Review(ctx, req)
	core_metrics.ReviewDuration.Observe(time.Since(start).Seconds())
	if err != nil {
		reason := "engine"
		var re *engine.RoleError
		switch {
		case errors.As(err, &re):
			reason = "role"
		case errors.Is(err, core_errors.ErrInvalidArgument):
			reason = "bad_file"
		}
		core_metrics.ReviewsFailed.WithLabelValues(reason).Inc()
		return core_domain.ContractReview{}, err
	}
	rev := core_domain.ContractReview{
		UserID: userID, TheirsName: req.Theirs.Name, Playbook: req.Playbook, PlaybookName: res.PlaybookName,
		OurRole: res.OurRole, Side: res.Side, Counts: res.Counts, Warnings: res.Warnings,
	}
	if req.Base != nil {
		rev.BaseName = req.Base.Name
	}
	out, err := s.repo.CreateReview(ctx, rev, core_domain.ReviewFiles{
		ReportHTML: []byte(res.ReportHTML), ReportXLSX: xlsx, Changes: res.Changes,
		Document: res.Document, Unified: res.Unified,
	})
	if err != nil {
		return core_domain.ContractReview{}, fmt.Errorf("save review: %w", err)
	}
	core_metrics.ReviewsCreated.Inc()
	return out, nil
}

func (s *ReviewsService) List(ctx context.Context, userID, limit, offset int) ([]core_domain.ContractReview, error) {
	if limit <= 0 {
		limit = DefaultLimit
	}
	if limit > MaxLimit+1 { // +1: приём «limit+1» для пагинации на фронтенде
		return nil, fmt.Errorf("limit must be at most %d: %w", MaxLimit+1, core_errors.ErrInvalidArgument)
	}
	if offset < 0 {
		return nil, fmt.Errorf("offset must be non-negative: %w", core_errors.ErrInvalidArgument)
	}
	return s.repo.ListReviews(ctx, userID, limit, offset)
}

func (s *ReviewsService) Get(ctx context.Context, userID, id int) (core_domain.ContractReview, error) {
	return s.repo.GetReview(ctx, userID, id)
}

func (s *ReviewsService) File(ctx context.Context, userID, id int, kind string) ([]byte, error) {
	return s.repo.GetFile(ctx, userID, id, kind)
}

func (s *ReviewsService) Delete(ctx context.Context, userID, id int) error {
	return s.repo.DeleteReview(ctx, userID, id)
}

func (s *ReviewsService) Choices(ctx context.Context, userID, id int) ([]core_domain.ReviewChoice, error) {
	return s.repo.ListChoices(ctx, userID, id)
}

func (s *ReviewsService) SaveChoice(ctx context.Context, userID, id int, c core_domain.ReviewChoice) error {
	if err := c.Validate(); err != nil {
		return err
	}
	return s.repo.SaveChoice(ctx, userID, id, c)
}

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
