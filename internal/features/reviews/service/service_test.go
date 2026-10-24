package reviews_service

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"github.com/Doomed07/Pravka/internal/engine"
	"go.uber.org/zap"
)

type fakeRepo struct {
	needIndex bool
	document  []byte
	paras     []core_domain.DocParagraph
	indexed   []int
	skipArg   []string
	missing   []core_domain.VectorChange
	vectors   map[string][]float32
	saves     int
	saved     []core_domain.ContractReview
	files     []core_domain.ReviewFiles
	listArg   [3]int
	choices   []core_domain.ReviewChoice
	project   core_domain.ProjectSummary // договор, который отдаёт GetProject; ID 0 — договора нет
	rounds    []core_domain.ProjectRound
	asked     [2]int // для кого и какой договор запрашивали
	review    core_domain.ContractReview
	cpDir     string          // папка контрагента, который отдаёт EnsureCounterparty
	cpEnsured []string        // названия контрагентов, которых просили найти или создать
	dirTaken  map[string]bool // занятые папки договоров
	queue     []int           // разборы, ждущие индексации (отдаются один раз)
	sourceErr map[int]error   // ошибка чтения исходных данных разбора
	mu        sync.Mutex
}

func (f *fakeRepo) CreateReview(_ context.Context, rev core_domain.ContractReview, files core_domain.ReviewFiles) (core_domain.ContractReview, error) {
	rev.ID = len(f.saved) + 1
	f.saved = append(f.saved, rev)
	f.files = append(f.files, files)
	return rev, nil
}
func (f *fakeRepo) ListReviews(_ context.Context, userID, limit, offset int) ([]core_domain.ContractReview, error) {
	f.listArg = [3]int{userID, limit, offset}
	return nil, nil
}
func (f *fakeRepo) GetReview(context.Context, int, int) (core_domain.ContractReview, error) {
	return f.review, nil
}
func (f *fakeRepo) GetFile(_ context.Context, _, _ int, kind string) ([]byte, error) {
	return []byte("file:" + kind), nil
}
func (f *fakeRepo) ListChoices(context.Context, int, int) ([]core_domain.ReviewChoice, error) {
	return f.choices, nil
}
func (f *fakeRepo) SaveChoice(_ context.Context, _, _ int, c core_domain.ReviewChoice) error {
	f.choices = append(f.choices, c)
	return nil
}
func (f *fakeRepo) DeleteReview(context.Context, int, int) error { return nil }
func (f *fakeRepo) ChangesWithoutVectors(context.Context, int, int) ([]core_domain.VectorChange, error) {
	return f.missing, nil
}
func (f *fakeRepo) SaveVectors(_ context.Context, _ int, model string, v map[string][]float32) error {
	if f.vectors == nil {
		f.vectors = map[string][]float32{}
	}
	for k, x := range v {
		f.vectors[k] = x
	}
	f.saves++
	return nil
}
func (f *fakeRepo) ReviewsToIndex(context.Context, int) ([]int, error) {
	q := f.queue
	f.queue = nil // очередь отдаём один раз: дальше в ней пусто
	return q, nil
}
func (f *fakeRepo) NeedsIndex(context.Context, int, int) (bool, error) { return f.needIndex, nil }
func (f *fakeRepo) IndexSource(_ context.Context, id int) ([]byte, []core_domain.VectorChange, error) {
	if err := f.sourceErr[id]; err != nil {
		return nil, nil, err
	}
	return f.document, f.missing, nil
}
func (f *fakeRepo) SaveParagraphs(_ context.Context, _ int, _ string, p []core_domain.DocParagraph, v [][]float32) error {
	if len(p) != len(v) {
		return fmt.Errorf("mismatch")
	}
	f.paras = append(f.paras, p...)
	return nil
}
func (f *fakeRepo) MarkIndexed(_ context.Context, id int) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.indexed = append(f.indexed, id)
	return nil
}

// indexedSafe — копия списка проиндексированных: индексатор работает в своей горутине.
func (f *fakeRepo) indexedSafe() []int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]int(nil), f.indexed...)
}
func (f *fakeRepo) ListWordings(context.Context, int, int) ([]core_domain.Wording, error) {
	return []core_domain.Wording{{ChangeID: "E001", Text: "прошлая редакция"}}, nil
}
func (f *fakeRepo) ListSemanticPrecedents(_ context.Context, _, _ int, skip []string) ([]core_domain.Precedent, error) {
	f.skipArg = skip
	return []core_domain.Precedent{{ChangeID: "E009", Choice: "counter", Semantic: true}}, nil
}
func (f *fakeRepo) ListLawHints(context.Context, int, int) ([]core_domain.LawHint, error) {
	return []core_domain.LawHint{{ChangeID: "E001", Article: "330"}}, nil
}
func (f *fakeRepo) ListPrecedents(context.Context, int, int) ([]core_domain.Precedent, error) {
	return []core_domain.Precedent{{ChangeID: "E001", Choice: "reject"}}, nil
}

func (f *fakeRepo) GetProject(_ context.Context, userID, id int) (core_domain.ProjectSummary, error) {
	f.asked = [2]int{userID, id}
	if f.project.ID == 0 || f.project.ID != id || f.project.UserID != userID {
		return core_domain.ProjectSummary{}, core_errors.ErrNotFound
	}
	return f.project, nil
}
func (f *fakeRepo) ListProjects(context.Context, int, int) ([]core_domain.ProjectSummary, error) {
	return []core_domain.ProjectSummary{f.project}, nil
}
func (f *fakeRepo) ListProjectRounds(context.Context, int, int) ([]core_domain.ProjectRound, error) {
	return f.rounds, nil
}

func (f *fakeRepo) EnsureCounterparty(_ context.Context, userID, id int, name, _ string) (core_domain.Counterparty, error) {
	f.cpEnsured = append(f.cpEnsured, name)
	return core_domain.Counterparty{ID: 5, UserID: userID, Name: name, Dir: f.cpDir}, nil
}
func (f *fakeRepo) AssignCounterpartyDir(_ context.Context, _, _ int, base string) (string, error) {
	f.cpDir = base
	return base, nil
}
func (f *fakeRepo) ProjectDirTaken(_ context.Context, dir string) (bool, error) {
	return f.dirTaken[dir], nil
}
func (f *fakeRepo) GetCounterparty(_ context.Context, userID, id int) (core_domain.CounterpartySummary, error) {
	if id != 5 {
		return core_domain.CounterpartySummary{}, core_errors.ErrNotFound
	}
	return core_domain.CounterpartySummary{Counterparty: core_domain.Counterparty{ID: id, UserID: userID, Name: "Ромашка"}}, nil
}
func (f *fakeRepo) ListCounterparties(context.Context, int, int) ([]core_domain.CounterpartySummary, error) {
	return nil, nil
}
func (f *fakeRepo) ListCounterpartyProjects(context.Context, int, int) ([]core_domain.ProjectSummary, error) {
	return nil, nil
}
func (f *fakeRepo) RenameCounterparty(context.Context, int, int, string, string) error { return nil }
func (f *fakeRepo) MoveProject(context.Context, int, int, int) error                   { return nil }

type fakeEngine struct {
	parties  core_domain.DetectedParties
	noEmbed  bool
	tries    int // сколько раз просили посчитать векторы, включая отказы
	embedded []string
	err      error
	calls    int
	got      core_domain.ReviewRequest
	ans      []string // что пришло в Answer: единая версия, правки, автор
	ansCh    []core_domain.ReviewChoice
}

func (f *fakeEngine) Answer(_ context.Context, unified, document, changes []byte, choices []core_domain.ReviewChoice, author string) (engine.AnswerResult, error) {
	f.ans, f.ansCh = []string{string(unified), string(changes), author, string(document)}, choices
	return engine.AnswerResult{DOCX: []byte("PKanswer")}, nil
}

func (f *fakeEngine) Parties(context.Context, core_domain.UploadedFile, string) (core_domain.DetectedParties, error) {
	return f.parties, f.err
}

func (f *fakeEngine) Embed(_ context.Context, texts []string) (string, [][]float32, error) {
	f.tries++
	if f.noEmbed {
		return "", nil, engine.ErrNoEmbedModel
	}
	f.embedded = append(f.embedded, texts...)
	out := make([][]float32, len(texts))
	for i := range texts {
		out[i] = []float32{float32(len(f.embedded) - len(texts) + i)}
	}
	return "bge-m3", out, nil
}

func (f *fakeEngine) Playbooks(context.Context) ([]core_domain.Playbook, error) { return nil, nil }
func (f *fakeEngine) Review(_ context.Context, r core_domain.ReviewRequest) (engine.Result, []byte, error) {
	f.calls++
	f.got = r
	if f.err != nil {
		return engine.Result{}, nil, f.err
	}
	return engine.Result{Counts: map[string]int{"всего": 3}, Warnings: []string{"w"}, PlaybookName: "pb", OurRole: "Заказчик",
		ContractType: "services",
		ReportHTML:   "<p>отчёт</p>", Changes: []byte(`[{"id":"E001"}]`), Document: []byte(`[{"index":0}]`),
		Unified: []byte("PKdocx")}, []byte("PKxlsx"), nil
}

var docx = core_domain.UploadedFile{Name: "C:\\Users\\юрист\\Договор 03.04.docx", Data: []byte("PK\x03\x04data")}

func TestCreate_SavesReportsNotContracts(t *testing.T) {
	repo, eng := &fakeRepo{}, &fakeEngine{}
	s := NewReviewsService(repo, eng)
	rev, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, Playbook: "private/x.yaml"})
	if err != nil {
		t.Fatal(err)
	}
	if rev.UserID != 7 || rev.TheirsName != "Договор 03.04.docx" || rev.Counts["всего"] != 3 || rev.OurRole != "Заказчик" ||
		repo.saved[0].ContractType != "services" {
		t.Errorf("saved review = %+v", rev)
	}
	f := repo.files[0]
	if string(f.ReportHTML) != "<p>отчёт</p>" || string(f.ReportXLSX) != "PKxlsx" || string(f.Changes) != `[{"id":"E001"}]` ||
		string(f.Document) != `[{"index":0}]` || string(f.Unified) != "PKdocx" {
		t.Errorf("saved files = %+v", f)
	}
}

func TestCreate_RejectsBadUploadsBeforeEngine(t *testing.T) {
	cases := map[string]core_domain.ReviewRequest{
		"empty":       {Theirs: core_domain.UploadedFile{Name: "a.docx"}},
		"not docx":    {Theirs: core_domain.UploadedFile{Name: "a.doc", Data: []byte("PK..")}},
		"pdf is zip":  {Theirs: core_domain.UploadedFile{Name: "a.pdf", Data: []byte("PK..")}},
		"not zip":     {Theirs: core_domain.UploadedFile{Name: "a.docx", Data: []byte("hello")}},
		"bad base":    {Theirs: docx, Base: &core_domain.UploadedFile{Name: "b.doc", Data: []byte("PK..")}},
		"long fields": {Theirs: docx, OurAuthors: string(make([]rune, 600))},
	}
	for name, req := range cases {
		t.Run(name, func(t *testing.T) {
			eng := &fakeEngine{}
			_, err := NewReviewsService(&fakeRepo{}, eng).Create(context.Background(), 1, req)
			if !errors.Is(err, core_errors.ErrInvalidArgument) {
				t.Fatalf("err = %v, want invalid argument", err)
			}
			if eng.calls != 0 {
				t.Errorf("engine called for invalid upload")
			}
		})
	}
}

func TestCreate_RoleErrorIsNotSaved(t *testing.T) {
	repo := &fakeRepo{}
	eng := &fakeEngine{err: &engine.RoleError{Message: "роль не подтверждена", Role: "Заказчик"}}
	_, err := NewReviewsService(repo, eng).Create(context.Background(), 1, core_domain.ReviewRequest{Theirs: docx})
	var re *engine.RoleError
	if !errors.As(err, &re) || re.Role != "Заказчик" || !errors.Is(err, core_errors.ErrUnprocessable) {
		t.Fatalf("err = %v", err)
	}
	if len(repo.saved) != 0 {
		t.Error("review saved despite role error")
	}
}

func TestCreate_EngineDown(t *testing.T) {
	eng := &fakeEngine{err: fmt.Errorf("dial: %w", core_errors.ErrUnavailable)}
	_, err := NewReviewsService(&fakeRepo{}, eng).Create(context.Background(), 1, core_domain.ReviewRequest{Theirs: docx})
	if !errors.Is(err, core_errors.ErrUnavailable) {
		t.Fatalf("err = %v", err)
	}
}

func TestList_Limits(t *testing.T) {
	repo := &fakeRepo{}
	s := NewReviewsService(repo, &fakeEngine{})
	if _, err := s.List(context.Background(), 3, 0, 0); err != nil || repo.listArg != [3]int{3, DefaultLimit, 0} {
		t.Errorf("default limit: err=%v args=%v", err, repo.listArg)
	}
	if _, err := s.List(context.Background(), 3, MaxLimit+2, 0); !errors.Is(err, core_errors.ErrInvalidArgument) {
		t.Errorf("too large limit: err=%v", err)
	}
	if _, err := s.List(context.Background(), 3, 10, -1); !errors.Is(err, core_errors.ErrInvalidArgument) {
		t.Errorf("negative offset: err=%v", err)
	}
}

func TestSaveChoice_ValidatesBeforeRepo(t *testing.T) {
	repo := &fakeRepo{}
	s := NewReviewsService(repo, &fakeEngine{})
	bad := []core_domain.ReviewChoice{
		{ChangeID: "E001; DROP", Choice: "accept"},
		{ChangeID: "E001", Choice: "maybe"},
		{ChangeID: "E001", Choice: "counter", Text: string(make([]rune, core_domain.MaxChoiceText+1))},
		{ChangeID: "E001", Choice: "edit", Text: "правка абзаца только у номера P…"},
		{ChangeID: "P012", Choice: "edit", Text: "  "},
		{ChangeID: "P012", Choice: "accept"},
	}
	for _, c := range bad {
		if err := s.SaveChoice(context.Background(), 1, 1, c); !errors.Is(err, core_errors.ErrInvalidArgument) {
			t.Errorf("%+v: err = %v, want invalid argument", c.ChangeID, err)
		}
	}
	if len(repo.choices) != 0 {
		t.Fatalf("invalid choices reached repo: %+v", repo.choices)
	}
	for _, c := range []core_domain.ReviewChoice{{ChangeID: "E001", Choice: "counter", Text: "30 дней"}, {ChangeID: "S002", Choice: ""},
		{ChangeID: "E003", Choice: "reply", Text: "Согласны."}, {ChangeID: "P012", Choice: "edit", Text: "Новый текст абзаца."},
		{ChangeID: "P012", Choice: ""}} {
		if err := s.SaveChoice(context.Background(), 1, 1, c); err != nil {
			t.Fatalf("%+v: %v", c, err)
		}
	}
}

func TestAnswer_SendsUnifiedChangesChoicesAndAuthor(t *testing.T) {
	repo := &fakeRepo{choices: []core_domain.ReviewChoice{{ChangeID: "E001", Choice: "reject"}}}
	eng := &fakeEngine{}
	res, err := NewReviewsService(repo, eng).Answer(context.Background(), 1, 3, "  Иванова А.  ")
	if err != nil || string(res.DOCX) != "PKanswer" {
		t.Fatalf("res = %q, err = %v", res.DOCX, err)
	}
	if eng.ans[0] != "file:docx" || eng.ans[1] != "file:changes" || eng.ans[2] != "Иванова А." || eng.ans[3] != "file:document" ||
		len(eng.ansCh) != 1 {
		t.Fatalf("engine got %q, choices %+v", eng.ans, eng.ansCh)
	}
	if _, err := NewReviewsService(repo, eng).Answer(context.Background(), 1, 3, string(make([]rune, MaxAuthor+1))); !errors.Is(err, core_errors.ErrInvalidArgument) {
		t.Fatalf("long author: err = %v", err)
	}
}

func TestLawHints_EmbedsMissingChangesInBatches(t *testing.T) {
	repo, eng := &fakeRepo{}, &fakeEngine{}
	for i := 0; i < 70; i++ {
		repo.missing = append(repo.missing, core_domain.VectorChange{ID: fmt.Sprintf("E%03d", i), Kind: "replace",
			Topic: "неустойка и штрафы", Context: "было", ContextAfter: fmt.Sprintf("стало %d", i)})
	}
	hints, err := NewReviewsService(repo, eng).LawHints(context.Background(), 1, 3)
	if err != nil || len(hints) != 1 || hints[0].Article != "330" {
		t.Fatalf("hints = %+v, err = %v", hints, err)
	}
	if repo.saves != 2 || len(repo.vectors) != 70 || eng.embedded[5] != "неустойка и штрафы. стало 5" || repo.vectors["E069"][0] != 69 {
		t.Fatalf("saves=%d vectors=%d first=%q", repo.saves, len(repo.vectors), eng.embedded[0])
	}
	// модели для векторов нет — подсказки из уже посчитанного, без ошибки
	repo2 := &fakeRepo{missing: repo.missing}
	if _, err := NewReviewsService(repo2, &fakeEngine{noEmbed: true}).LawHints(context.Background(), 1, 3); err != nil || repo2.saves != 0 {
		t.Fatalf("no model: err = %v, saves = %d", err, repo2.saves)
	}
}

func TestPrecedents_WordsFirstThenSenseForTheRest(t *testing.T) {
	repo := &fakeRepo{}
	got, err := NewReviewsService(repo, &fakeEngine{}).Precedents(context.Background(), 1, 3)
	if err != nil || len(got) != 2 || got[0].ChangeID != "E001" || got[0].Semantic || !got[1].Semantic {
		t.Fatalf("got %+v, err = %v", got, err)
	}
	if len(repo.skipArg) != 1 || repo.skipArg[0] != "E001" {
		t.Fatalf("edits with word precedents are skipped in the semantic search: %v", repo.skipArg)
	}
}

func TestIndexReview_ParagraphsAndChangesThenMarked(t *testing.T) {
	doc := `[{"index":4,"clause":"3.1","segments":[{"k":"equal","t":"Поставщик поставляет Товар в течение тридцати календарных дней."}]},
	{"index":5,"clause":"3.2","segments":[{"k":"equal","t":"Коротко."}]}]`
	repo := &fakeRepo{needIndex: true, document: []byte(doc),
		missing: []core_domain.VectorChange{{ID: "E001", Kind: "replace", Topic: "сроки исполнения", ContextAfter: "10 дней"}}}
	eng := &fakeEngine{}
	if _, err := NewReviewsService(repo, eng).Wordings(context.Background(), 1, 7); err != nil {
		t.Fatal(err)
	}
	if len(repo.paras) != 1 || repo.paras[0].Index != 4 || len(repo.vectors) != 1 || len(repo.indexed) != 1 || repo.indexed[0] != 7 {
		t.Fatalf("paras=%+v vectors=%d indexed=%v", repo.paras, len(repo.vectors), repo.indexed)
	}
	// модели нет — разбор не помечается проиндексированным, подсказки отдаются без ошибки
	repo2 := &fakeRepo{needIndex: true, document: []byte(doc)}
	if _, err := NewReviewsService(repo2, &fakeEngine{noEmbed: true}).Wordings(context.Background(), 1, 7); err != nil || len(repo2.indexed) != 0 {
		t.Fatalf("no model: err = %v, indexed = %v", err, repo2.indexed)
	}
}

func TestCreate_NewProjectGetsNameFromEnteredOrFile(t *testing.T) {
	repo := &fakeRepo{}
	s := NewReviewsService(repo, &fakeEngine{})
	if _, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx}); err != nil {
		t.Fatal(err)
	}
	if got := repo.saved[0]; got.ProjectID != 0 || got.ProjectName != "Договор 03.04" {
		t.Errorf("по умолчанию — имя файла без .docx: %+v", got)
	}
	if _, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, ProjectName: "  Поставка   Омега "}); err != nil {
		t.Fatal(err)
	}
	if got := repo.saved[1]; got.ProjectName != "Поставка Омега" {
		t.Errorf("введённое название: %+v", got)
	}
	eng := &fakeEngine{}
	_, err := NewReviewsService(&fakeRepo{}, eng).Create(context.Background(), 7,
		core_domain.ReviewRequest{Theirs: docx, ProjectName: strings.Repeat("я", 300)})
	if !errors.Is(err, core_errors.ErrInvalidArgument) || eng.calls != 0 {
		t.Errorf("слишком длинное название договора: err = %v, engine calls = %d", err, eng.calls)
	}
}

func TestCreate_NextRoundOfProject(t *testing.T) {
	proj := core_domain.ProjectSummary{Project: core_domain.Project{ID: 5, UserID: 7, Name: "Поставка Омега"}, Rounds: 1,
		OurRole: "Заказчик"}
	repo := &fakeRepo{project: proj}
	eng := &fakeEngine{}
	rev, err := NewReviewsService(repo, eng).Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, ProjectID: 5})
	if err != nil {
		t.Fatal(err)
	}
	if got := repo.saved[0]; got.ProjectID != 5 || got.ProjectName != "" || rev.ProjectID != 5 {
		t.Errorf("очередной раунд записывается в тот же договор: %+v", got)
	}
}

func TestCreate_ProjectGuards(t *testing.T) {
	proj := core_domain.ProjectSummary{Project: core_domain.Project{ID: 5, UserID: 7, Name: "Поставка Омега"}, OurRole: "Поставщик"}
	// чужой или несуществующий договор — 404 до долгого разбора
	repo, eng := &fakeRepo{project: proj}, &fakeEngine{}
	_, err := NewReviewsService(repo, eng).Create(context.Background(), 8, core_domain.ReviewRequest{Theirs: docx, ProjectID: 5})
	if !errors.Is(err, core_errors.ErrNotFound) || eng.calls != 0 || len(repo.saved) != 0 {
		t.Fatalf("чужой договор: err = %v, engine calls = %d, saved = %d", err, eng.calls, len(repo.saved))
	}
	// плейбук за другую роль, чем в прошлых раундах (движок вернул «Заказчик»), — не сохраняем
	repo = &fakeRepo{project: proj}
	_, err = NewReviewsService(repo, &fakeEngine{}).Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, ProjectID: 5})
	if !errors.Is(err, core_errors.ErrInvalidArgument) || len(repo.saved) != 0 {
		t.Fatalf("другая роль: err = %v, saved = %d", err, len(repo.saved))
	}
	for _, want := range []string{"Поставка Омега", "Поставщик", "Заказчик"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("в сообщении нет %q: %v", want, err)
		}
	}
	// у прошлых раундов роли не было (разбор без плейбука) — проверять нечего
	proj.OurRole = ""
	repo = &fakeRepo{project: proj}
	if _, err := NewReviewsService(repo, &fakeEngine{}).Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, ProjectID: 5}); err != nil {
		t.Fatalf("роли в договоре нет: %v", err)
	}
}

func roundRepo() *fakeRepo {
	changes := func(fp, clause, after string) []byte {
		return []byte(`[{"id":"E001","fingerprint":"` + fp + `","clause":"` + clause + `","topic":"порядок и сроки оплаты","kind":"replace",` +
			`"before":"30%","after":"` + after + `","materiality":"высокая"}]`)
	}
	return &fakeRepo{
		project: core_domain.ProjectSummary{Project: core_domain.Project{ID: 5, UserID: 7, Name: "Поставка"}, Rounds: 4},
		review:  core_domain.ContractReview{ID: 12, UserID: 7, ProjectID: 5, Round: 2},
		rounds: []core_domain.ProjectRound{
			{ReviewID: 11, Round: 1, Changes: changes("a", "2.2", "10%"),
				Choices: []core_domain.ReviewChoice{{ChangeID: "E001", Choice: core_domain.ChoiceReject}}},
			{ReviewID: 12, Round: 2, Changes: changes("a", "2.2", "10%")},
			{ReviewID: 13, Round: 3, Changes: changes("b", "2.2", "15%")},
			{ReviewID: 14, Round: 4, Changes: changes("c", "9.9", "40%")}, // к пункту 2.2 контрагент больше не вернулся
		},
	}
}

func TestRounds_ComparesWithEarlierRoundsOnly(t *testing.T) {
	v, err := NewReviewsService(roundRepo(), &fakeEngine{}).Rounds(context.Background(), 7, 12)
	if err != nil {
		t.Fatal(err)
	}
	if v.Round != 2 || v.PrevReviewID != 11 || v.Project.Name != "Поставка" || len(v.Comparison.Links) != 1 {
		t.Fatalf("rounds = %+v", v)
	}
	// раунд 3 (правка «15%») в сравнение раунда 2 не входит: правка раунда 2 — повтор раунда 1, решение «отклонить» видно
	if l := v.Comparison.Links[0]; l.Relation != core_domain.RelationRepeat || l.ReviewID != 11 || l.Decision != core_domain.ChoiceReject {
		t.Errorf("link = %+v", l)
	}
	later := roundRepo()
	later.review.ID, later.review.Round = 14, 4
	if v4, err := NewReviewsService(later, &fakeEngine{}).Rounds(context.Background(), 7, 14); err != nil || v4.PrevReviewID != 13 ||
		len(v4.Comparison.Closed) != 1 || v4.Comparison.Closed[0].ReviewID != 13 {
		t.Errorf("раунд 4: %+v, %v", v4, err)
	}
	first, err := NewReviewsService(func() *fakeRepo { r := roundRepo(); r.review.ID, r.review.Round = 11, 1; return r }(), &fakeEngine{}).
		Rounds(context.Background(), 7, 11)
	if err != nil || first.PrevReviewID != 0 || first.Comparison.Count(core_domain.RelationNew) != 1 {
		t.Errorf("первый раунд: %+v, %v", first, err)
	}
}

func TestProject_HistoryCountsPerRound(t *testing.T) {
	v, err := NewReviewsService(roundRepo(), &fakeEngine{}).Project(context.Background(), 7, 5)
	if err != nil {
		t.Fatal(err)
	}
	if len(v.Rounds) != 4 {
		t.Fatalf("rounds = %+v", v.Rounds)
	}
	r1, r2, r3, r4 := v.Rounds[0], v.Rounds[1], v.Rounds[2], v.Rounds[3]
	if r1.New != 1 || r1.Repeat != 0 || r1.Closed != 0 || r1.Total != 1 {
		t.Errorf("раунд 1 = %+v", r1)
	}
	if r2.Repeat != 1 || r2.New != 0 || r2.Closed != 0 {
		t.Errorf("раунд 2 = %+v", r2)
	}
	if r3.Returned != 1 || r3.Repeat != 0 || r3.Closed != 0 || r3.ReviewID != 13 {
		t.Errorf("раунд 3 = %+v", r3)
	}
	if r4.New != 1 || r4.Closed != 1 || r4.Repeat != 0 || r4.Returned != 0 {
		t.Errorf("раунд 4: правка раунда 3 снята, новая — по другому пункту: %+v", r4)
	}
	if _, err := NewReviewsService(roundRepo(), &fakeEngine{}).Project(context.Background(), 8, 5); !errors.Is(err, core_errors.ErrNotFound) {
		t.Errorf("чужой договор: %v", err)
	}
}

func TestCreate_AcceptsOdtAndPdf(t *testing.T) {
	for _, f := range []core_domain.UploadedFile{{Name: "a.odt", Data: []byte("PK\x03\x04")}, {Name: "a.pdf", Data: []byte("%PDF-1.7")}} {
		eng := &fakeEngine{}
		repo := &fakeRepo{}
		base := core_domain.UploadedFile{Name: "base.docx", Data: []byte("PK\x03\x04")}
		if _, err := NewReviewsService(repo, eng).Create(context.Background(), 1, core_domain.ReviewRequest{Theirs: f, Base: &base}); err != nil {
			t.Errorf("%s: %v", f.Name, err)
		}
		if eng.calls != 1 || repo.saved[0].TheirsName != f.Name {
			t.Errorf("%s: engine calls = %d, saved = %+v", f.Name, eng.calls, repo.saved)
		}
	}
}

func TestEmbedChanges_SkipsChangesWithoutText(t *testing.T) {
	// правки без текста (убран пустой абзац) встречаются в настоящих договорах; пустую строку движок не принимает
	repo := &fakeRepo{missing: []core_domain.VectorChange{
		{ID: "E001", Kind: "delete", Topic: "прочее"},
		{ID: "E002", Kind: "replace", Topic: "сроки исполнения", ContextAfter: "10 дней"},
		{ID: "E003", Kind: "delete", Context: "   "},
	}}
	eng := &fakeEngine{}
	if _, err := NewReviewsService(repo, eng).LawHints(context.Background(), 1, 7); err != nil {
		t.Fatal(err)
	}
	if len(eng.embedded) != 1 || !strings.Contains(eng.embedded[0], "10 дней") {
		t.Fatalf("в движок ушло %q, want только текст правки E002", eng.embedded)
	}
	if _, ok := repo.vectors["E002"]; !ok || len(repo.vectors) != 1 {
		t.Errorf("векторы сохранены для %v, want только E002", repo.vectors)
	}
	// все правки без текста: к движку не обращаемся совсем
	repo = &fakeRepo{missing: []core_domain.VectorChange{{ID: "E001", Kind: "delete"}}}
	eng = &fakeEngine{}
	if _, err := NewReviewsService(repo, eng).LawHints(context.Background(), 1, 7); err != nil || len(eng.embedded) != 0 {
		t.Fatalf("err = %v, embedded = %q", err, eng.embedded)
	}
}

func TestRunIndexer_OneFailingReviewDoesNotBlockTheQueue(t *testing.T) {
	repo := &fakeRepo{queue: []int{1, 2, 3}, document: []byte(`[]`), sourceErr: map[int]error{1: errors.New("повреждённые данные")}}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		NewReviewsService(repo, &fakeEngine{}).RunIndexer(ctx, &core_logger.Logger{Logger: zap.NewNop()})
		close(done)
	}()
	deadline := time.Now().Add(2 * time.Second)
	for len(repo.indexedSafe()) < 2 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	cancel()
	<-done
	if got := repo.indexedSafe(); len(got) != 2 || got[0] != 2 || got[1] != 3 {
		t.Fatalf("проиндексированы %v, want [2 3]: неудача разбора 1 не должна останавливать очередь", got)
	}
}

func TestRunIndexer_NoModelStopsTheQueue(t *testing.T) {
	repo := &fakeRepo{queue: []int{1, 2}, document: []byte(`[]`), missing: []core_domain.VectorChange{{ID: "E001", Kind: "replace", ContextAfter: "10 дней"}}}
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	eng := &fakeEngine{noEmbed: true}
	NewReviewsService(repo, eng).RunIndexer(ctx, &core_logger.Logger{Logger: zap.NewNop()})
	if got := repo.indexedSafe(); len(got) != 0 || eng.tries != 1 {
		t.Fatalf("без модели проиндексированы %v, обращений к движку %d; want [] и 1: остальным разборам нечем считать", got, eng.tries)
	}
}
