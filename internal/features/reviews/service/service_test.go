package reviews_service

import (
	"context"
	"errors"
	"fmt"
	"testing"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	"github.com/Doomed07/Pravka/internal/engine"
)

type fakeRepo struct {
	missing []core_domain.VectorChange
	vectors map[string][]float32
	saves   int
	saved   []core_domain.ContractReview
	files   []core_domain.ReviewFiles
	listArg [3]int
	choices []core_domain.ReviewChoice
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
	return core_domain.ContractReview{}, nil
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
func (f *fakeRepo) ListLawHints(context.Context, int, int) ([]core_domain.LawHint, error) {
	return []core_domain.LawHint{{ChangeID: "E001", Article: "330"}}, nil
}
func (f *fakeRepo) ListPrecedents(context.Context, int, int) ([]core_domain.Precedent, error) {
	return []core_domain.Precedent{{ChangeID: "E001", Choice: "reject"}}, nil
}

type fakeEngine struct {
	noEmbed  bool
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

func (f *fakeEngine) Embed(_ context.Context, texts []string) (string, [][]float32, error) {
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
		"not docx":    {Theirs: core_domain.UploadedFile{Name: "a.pdf", Data: []byte("PK..")}},
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
		{ChangeID: "E003", Choice: "reply", Text: "Согласны."}} {
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
