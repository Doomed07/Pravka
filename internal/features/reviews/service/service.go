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
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
	"github.com/Doomed07/Pravka/internal/engine"
	"go.uber.org/zap"
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
	ListPrecedents(ctx context.Context, userID, reviewID int) ([]core_domain.Precedent, error)
	ChangesWithoutVectors(ctx context.Context, userID, reviewID int) ([]core_domain.VectorChange, error)
	SaveVectors(ctx context.Context, reviewID int, model string, vectors map[string][]float32) error
	ListLawHints(ctx context.Context, userID, reviewID int) ([]core_domain.LawHint, error)
	ReviewsToIndex(ctx context.Context, limit int) ([]int, error)
	NeedsIndex(ctx context.Context, userID, reviewID int) (bool, error)
	IndexSource(ctx context.Context, reviewID int) ([]byte, []core_domain.VectorChange, error)
	SaveParagraphs(ctx context.Context, reviewID int, model string, paras []core_domain.DocParagraph, vectors [][]float32) error
	MarkIndexed(ctx context.Context, reviewID int) error
	ListWordings(ctx context.Context, userID, reviewID int) ([]core_domain.Wording, error)
	ListSemanticPrecedents(ctx context.Context, userID, reviewID int, skip []string) ([]core_domain.Precedent, error)
}

type Engine interface {
	Playbooks(ctx context.Context) ([]core_domain.Playbook, error)
	Review(ctx context.Context, r core_domain.ReviewRequest) (engine.Result, []byte, error)
	Answer(ctx context.Context, unified, document, changes []byte, choices []core_domain.ReviewChoice, author string) (engine.AnswerResult, error)
	Embed(ctx context.Context, texts []string) (string, [][]float32, error)
}

type ReviewsService struct {
	repo   ReviewsRepository
	engine Engine
	nudge  chan struct{} // новый разбор: фоновой индексации пора проснуться
}

func NewReviewsService(repo ReviewsRepository, eng Engine) *ReviewsService {
	return &ReviewsService{repo: repo, engine: eng, nudge: make(chan struct{}, 1)}
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
		OurRole: res.OurRole, ContractType: res.ContractType, Side: res.Side, Counts: res.Counts, Warnings: res.Warnings,
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
	select {
	case s.nudge <- struct{}{}:
	default:
	}
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

// Wordings — «ваши прошлые формулировки» к правкам разбора: похожие пункты из нашей редакции в прошлых разборах.
func (s *ReviewsService) Wordings(ctx context.Context, userID, id int) ([]core_domain.Wording, error) {
	if err := s.indexIfNeeded(ctx, userID, id); err != nil {
		return nil, err
	}
	return s.repo.ListWordings(ctx, userID, id)
}

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

// embedBatch — текстов за один запрос векторов (предел движка).
const embedBatch = 64

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
