package reviews_service

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"github.com/Doomed07/Pravka/internal/features/reviews/filestore"
	"go.uber.org/zap"
)

func read(t *testing.T, parts ...string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(parts...))
	if err != nil {
		t.Fatalf("файл не найден: %v", err)
	}
	return string(b)
}

func TestCreate_NewContractPutsFirstVersionIntoCounterpartyFolder(t *testing.T) {
	root := t.TempDir()
	repo := &fakeRepo{}
	s := NewReviewsService(repo, &fakeEngine{}, WithFiles(filestore.New(root)))
	_, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx,
		CounterpartyName: "  ООО  «Ромашка» ", ProjectName: "Договор поставки"})
	if err != nil {
		t.Fatal(err)
	}
	if got := repo.cpEnsured; len(got) != 1 || got[0] != "ООО «Ромашка»" {
		t.Errorf("контрагент = %v", got)
	}
	if repo.saved[0].ProjectDir != "ООО «Ромашка»/Договор поставки" || repo.saved[0].CounterpartyID != 5 {
		t.Errorf("сохранено = %+v", repo.saved[0])
	}
	if got := read(t, root, "ООО «Ромашка»", "Договор поставки", "Раунд 1", "01 Версия контрагента.docx"); got != string(docx.Data) {
		t.Errorf("содержимое файла = %q", got)
	}
}

func TestCreate_NoCounterpartyGoesToDefaultOne(t *testing.T) {
	repo := &fakeRepo{}
	s := NewReviewsService(repo, &fakeEngine{})
	if _, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx}); err != nil {
		t.Fatal(err)
	}
	if repo.cpEnsured[0] != core_domain.NoCounterparty || repo.saved[0].ProjectDir != "" {
		t.Errorf("контрагент %v, папка %q: хранилище выключено — папки нет", repo.cpEnsured, repo.saved[0].ProjectDir)
	}
}

func TestCreate_SameNameContractGetsSuffixedFolder(t *testing.T) {
	root := t.TempDir()
	repo := &fakeRepo{dirTaken: map[string]bool{"Ромашка/Договор": true, "Ромашка/Договор 2": true}}
	s := NewReviewsService(repo, &fakeEngine{}, WithFiles(filestore.New(root)))
	if _, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, CounterpartyName: "Ромашка", ProjectName: "Договор"}); err != nil {
		t.Fatal(err)
	}
	if repo.saved[0].ProjectDir != "Ромашка/Договор 3" {
		t.Errorf("папка = %q", repo.saved[0].ProjectDir)
	}
}

func TestCreate_NextRoundGoesToNextRoundFolderOfTheSameContract(t *testing.T) {
	root := t.TempDir()
	repo := &fakeRepo{project: core_domain.ProjectSummary{
		Project: core_domain.Project{ID: 3, UserID: 7, Name: "Договор", Dir: "Ромашка/Договор"}, Rounds: 2}}
	s := NewReviewsService(repo, &fakeEngine{}, WithFiles(filestore.New(root)))
	if _, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, ProjectID: 3}); err != nil {
		t.Fatal(err)
	}
	read(t, root, "Ромашка", "Договор", "Раунд 3", "01 Версия контрагента.docx")
	if len(repo.cpEnsured) != 0 {
		t.Errorf("контрагента для существующего договора не ищем: %v", repo.cpEnsured)
	}
}

func TestCreate_PdfKeepsItsExtension(t *testing.T) {
	root := t.TempDir()
	repo := &fakeRepo{}
	s := NewReviewsService(repo, &fakeEngine{}, WithFiles(filestore.New(root)))
	pdf := core_domain.UploadedFile{Name: "Договор.pdf", Data: []byte("%PDF-1.4 x")}
	base := core_domain.UploadedFile{Name: "наш.docx", Data: []byte("PK\x03\x04")}
	if _, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: pdf, Base: &base, CounterpartyName: "Ромашка"}); err != nil {
		t.Fatal(err)
	}
	read(t, root, "Ромашка", "Договор", "Раунд 1", "01 Версия контрагента.pdf")
}

func TestCreate_DiskFailureKeepsReviewAndWarns(t *testing.T) {
	root := t.TempDir()
	blocker := filepath.Join(root, "Ромашка") // на месте папки контрагента лежит файл: записать нельзя
	if err := os.WriteFile(blocker, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	repo := &fakeRepo{}
	s := NewReviewsService(repo, &fakeEngine{}, WithFiles(filestore.New(root)))
	ctx := core_logger.ToCtx(context.Background(), &core_logger.Logger{Logger: zap.NewNop()})
	rev, err := s.Create(ctx, 7, core_domain.ReviewRequest{Theirs: docx, CounterpartyName: "Ромашка"})
	if err != nil || len(repo.saved) != 1 {
		t.Fatalf("разбор не сохранён: %v", err)
	}
	last := rev.Warnings[len(rev.Warnings)-1]
	if !strings.Contains(last, "не сохранён в папку на диске") {
		t.Errorf("предупреждения = %v", rev.Warnings)
	}
}

func TestCreate_RejectsForeignCounterpartyBeforeEngine(t *testing.T) {
	eng := &fakeEngine{}
	_, err := NewReviewsService(&fakeRepo{}, eng).Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, CounterpartyID: 99})
	if !errors.Is(err, core_errors.ErrNotFound) || eng.calls != 0 {
		t.Errorf("err = %v, вызовов движка %d", err, eng.calls)
	}
	_, err = NewReviewsService(&fakeRepo{}, eng).Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, CounterpartyINN: "123"})
	if !errors.Is(err, core_errors.ErrInvalidArgument) || eng.calls != 0 {
		t.Errorf("ИНН: err = %v", err)
	}
}

func TestAnswer_IsSavedNextToTheirVersion(t *testing.T) {
	root := t.TempDir()
	repo := &fakeRepo{
		review:  core_domain.ContractReview{ID: 3, ProjectID: 3, Round: 2},
		project: core_domain.ProjectSummary{Project: core_domain.Project{ID: 3, UserID: 1, Dir: "Ромашка/Договор"}},
	}
	s := NewReviewsService(repo, &fakeEngine{}, WithFiles(filestore.New(root)))
	if _, err := s.Answer(context.Background(), 1, 3, "Иванова А."); err != nil {
		t.Fatal(err)
	}
	if got := read(t, root, "Ромашка", "Договор", "Раунд 2", "02 Наша версия с ответами.docx"); got != "PKanswer" {
		t.Errorf("ответ = %q", got)
	}
}

func TestAnswer_OldContractWithoutFolderIsNotSaved(t *testing.T) {
	root := t.TempDir()
	repo := &fakeRepo{
		review:  core_domain.ContractReview{ID: 3, ProjectID: 3, Round: 1},
		project: core_domain.ProjectSummary{Project: core_domain.Project{ID: 3, UserID: 1}},
	}
	s := NewReviewsService(repo, &fakeEngine{}, WithFiles(filestore.New(root)))
	if _, err := s.Answer(context.Background(), 1, 3, "x"); err != nil {
		t.Fatal(err)
	}
	if entries, _ := os.ReadDir(root); len(entries) != 0 {
		t.Errorf("записано для договора без папки: %v", entries)
	}
}

func TestDetectParties_ValidatesFileBeforeEngine(t *testing.T) {
	eng := &fakeEngine{parties: core_domain.DetectedParties{Counterparty: &core_domain.DetectedParty{Name: "Бета"}}}
	s := NewReviewsService(&fakeRepo{}, eng)
	got, err := s.DetectParties(context.Background(), docx, "7701234567")
	if err != nil || got.Counterparty == nil || got.Counterparty.Name != "Бета" {
		t.Fatalf("got %+v, %v", got, err)
	}
	if _, err := s.DetectParties(context.Background(), core_domain.UploadedFile{Name: "a.docx", Data: []byte("hello")}, ""); !errors.Is(err, core_errors.ErrInvalidArgument) {
		t.Errorf("не договор: err = %v", err)
	}
}

func TestCreate_FirstVersionOnlyForNewContract(t *testing.T) {
	repo := &fakeRepo{project: core_domain.ProjectSummary{Project: core_domain.Project{ID: 3, UserID: 7}, Rounds: 1}}
	eng := &fakeEngine{}
	s := NewReviewsService(repo, eng)
	if _, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, FirstVersion: true}); err != nil || !eng.got.FirstVersion {
		t.Fatalf("новый договор: первая версия передаётся движку: %v, %+v", err, eng.got)
	}
	if _, err := s.Create(context.Background(), 7, core_domain.ReviewRequest{Theirs: docx, FirstVersion: true, ProjectID: 3}); err != nil || eng.got.FirstVersion {
		t.Fatalf("очередной раунд не может быть первой версией: %v, %+v", err, eng.got)
	}
}
