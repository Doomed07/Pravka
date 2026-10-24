package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	"github.com/Doomed07/Pravka/internal/engine"
	"github.com/Doomed07/Pravka/internal/features/reviews/filestore"
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
	GetProject(ctx context.Context, userID, id int) (core_domain.ProjectSummary, error)
	ListProjects(ctx context.Context, userID, limit int) ([]core_domain.ProjectSummary, error)
	ListProjectRounds(ctx context.Context, userID, projectID int) ([]core_domain.ProjectRound, error)
	EnsureCounterparty(ctx context.Context, userID, id int, name, inn string) (core_domain.Counterparty, error)
	AssignCounterpartyDir(ctx context.Context, userID, id int, base string) (string, error)
	ProjectDirTaken(ctx context.Context, dir string) (bool, error)
	GetCounterparty(ctx context.Context, userID, id int) (core_domain.CounterpartySummary, error)
	ListCounterparties(ctx context.Context, userID, limit int) ([]core_domain.CounterpartySummary, error)
	ListCounterpartyProjects(ctx context.Context, userID, counterpartyID int) ([]core_domain.ProjectSummary, error)
	RenameCounterparty(ctx context.Context, userID, id int, name, inn string) error
	MoveProject(ctx context.Context, userID, projectID, counterpartyID int) error
	DeleteProject(ctx context.Context, userID, id int) error
}

type Engine interface {
	Playbooks(ctx context.Context) ([]core_domain.Playbook, error)
	Review(ctx context.Context, r core_domain.ReviewRequest) (engine.Result, []byte, error)
	Answer(ctx context.Context, unified, document, changes []byte, choices []core_domain.ReviewChoice, author string) (engine.AnswerResult, error)
	Embed(ctx context.Context, texts []string) (string, [][]float32, error)
	Parties(ctx context.Context, theirs core_domain.UploadedFile, company string) (core_domain.DetectedParties, error)
}

type ReviewsService struct {
	repo   ReviewsRepository
	engine Engine
	files  *filestore.Store // папки на диске: Контрагент / Договор / Раунд N; выключено, если корень не задан
	nudge  chan struct{}    // новый разбор: фоновой индексации пора проснуться
}

// Option — необязательная настройка сервиса.
type Option func(*ReviewsService)

// WithFiles включает сохранение файлов раундов в папки на диске.
func WithFiles(store *filestore.Store) Option {
	return func(s *ReviewsService) { s.files = store }
}

func NewReviewsService(repo ReviewsRepository, eng Engine, opts ...Option) *ReviewsService {
	s := &ReviewsService{repo: repo, engine: eng, nudge: make(chan struct{}, 1)}
	for _, o := range opts {
		o(s)
	}
	return s
}

// embedBatch — текстов за один запрос векторов (предел движка).
const embedBatch = 64
