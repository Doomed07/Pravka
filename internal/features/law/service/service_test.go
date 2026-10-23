package law_service

import (
	"context"
	"fmt"
	"testing"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	"github.com/Doomed07/Pravka/internal/engine"
)

type fakeRepo struct {
	version, model string
	points         []core_domain.LawPoint
	withVec        int
	clears         int
}

func (f *fakeRepo) Meta(context.Context, string) (string, string, error) { return f.version, f.model, nil }
func (f *fakeRepo) Clear(context.Context, string) error {
	f.clears++
	f.points, f.withVec, f.version, f.model = nil, 0, "", ""
	return nil
}
func (f *fakeRepo) Insert(_ context.Context, p []core_domain.LawPoint, v [][]float32) error {
	f.points = append(f.points, p...)
	if v != nil {
		f.withVec += len(v)
	}
	return nil
}
func (f *fakeRepo) SetMeta(_ context.Context, _, version, model string) error {
	f.version, f.model = version, model
	return nil
}

type fakeEngine struct {
	version  string
	total    int
	noModel  bool
	embedded int
}

func (f *fakeEngine) Law(_ context.Context, offset, limit int) (engine.LawPage, error) {
	page := engine.LawPage{Version: f.version, Total: f.total}
	for i := offset; i < min(offset+limit, f.total); i++ {
		page.Points = append(page.Points, core_domain.LawPoint{Code: Code, Article: fmt.Sprint(i), Title: "т", Text: "текст"})
	}
	return page, nil
}
func (f *fakeEngine) Embed(_ context.Context, texts []string) (string, [][]float32, error) {
	if f.noModel {
		return "", nil, engine.ErrNoEmbedModel
	}
	f.embedded += len(texts)
	return "bge-m3", make([][]float32, len(texts)), nil
}

func TestSync_LoadsAllPagesWithVectorsOnce(t *testing.T) {
	repo, eng := &fakeRepo{}, &fakeEngine{version: "v1", total: 1234}
	s := NewLawService(repo, eng)
	ok, err := s.Sync(context.Background())
	if err != nil || !ok || len(repo.points) != 1234 || repo.withVec != 1234 || repo.version != "v1" || repo.model != "bge-m3" {
		t.Fatalf("ok=%v err=%v points=%d vec=%d meta=%s/%s", ok, err, len(repo.points), repo.withVec, repo.version, repo.model)
	}
	// та же версия, векторы есть — повторно не грузим
	if ok, err := s.Sync(context.Background()); err != nil || !ok || repo.clears != 1 || eng.embedded != 1234 {
		t.Fatalf("second sync reloaded: clears=%d embedded=%d", repo.clears, eng.embedded)
	}
	// новый текст закона — загрузка заново
	eng.version = "v2"
	if _, err := s.Sync(context.Background()); err != nil || repo.clears != 2 || repo.version != "v2" || len(repo.points) != 1234 {
		t.Fatalf("new version: clears=%d version=%s points=%d", repo.clears, repo.version, len(repo.points))
	}
}

func TestSync_WithoutModelLoadsWordsOnlyAndRetriesVectors(t *testing.T) {
	repo, eng := &fakeRepo{}, &fakeEngine{version: "v1", total: 100, noModel: true}
	s := NewLawService(repo, eng)
	ok, err := s.Sync(context.Background())
	if err != nil || ok || len(repo.points) != 100 || repo.withVec != 0 || repo.version != "v1" || repo.model != "" {
		t.Fatalf("no model: ok=%v err=%v points=%d meta=%q/%q", ok, err, len(repo.points), repo.version, repo.model)
	}
	eng.noModel = false // модель появилась — векторы досчитываются
	if ok, err := s.Sync(context.Background()); err != nil || !ok || repo.withVec != 100 || repo.model != "bge-m3" {
		t.Fatalf("model back: ok=%v err=%v vec=%d model=%q", ok, err, repo.withVec, repo.model)
	}
}
