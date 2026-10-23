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
	saved   []core_domain.ContractReview
	files   []core_domain.ReviewFiles
	listArg [3]int
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
func (f *fakeRepo) GetFile(context.Context, int, int, string) ([]byte, error) { return nil, nil }
func (f *fakeRepo) DeleteReview(context.Context, int, int) error              { return nil }

type fakeEngine struct {
	err   error
	calls int
	got   core_domain.ReviewRequest
}

func (f *fakeEngine) Playbooks(context.Context) ([]core_domain.Playbook, error) { return nil, nil }
func (f *fakeEngine) Review(_ context.Context, r core_domain.ReviewRequest) (engine.Result, []byte, error) {
	f.calls++
	f.got = r
	if f.err != nil {
		return engine.Result{}, nil, f.err
	}
	return engine.Result{Counts: map[string]int{"всего": 3}, Warnings: []string{"w"}, PlaybookName: "pb", OurRole: "Заказчик",
		ReportHTML: "<p>отчёт</p>", Changes: []byte(`[{"id":"E001"}]`), Document: []byte(`[{"index":0}]`),
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
	if rev.UserID != 7 || rev.TheirsName != "Договор 03.04.docx" || rev.Counts["всего"] != 3 || rev.OurRole != "Заказчик" {
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
