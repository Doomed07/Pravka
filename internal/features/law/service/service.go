package law_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	"github.com/Doomed07/Pravka/internal/engine"
)

// Code — какой закон загружается. Пока один: ГК РФ.
const Code = "ГК РФ"

const (
	pageSize  = 500 // пунктов за один запрос к движку
	embedSize = 64  // текстов за один запрос векторов (предел движка)
	maxText   = 2000
)

type Repository interface {
	Meta(ctx context.Context, code string) (version, model string, err error)
	Clear(ctx context.Context, code string) error
	Insert(ctx context.Context, points []core_domain.LawPoint, vectors [][]float32) error
	SetMeta(ctx context.Context, code, version, model string) error
}

type Engine interface {
	Law(ctx context.Context, offset, limit int) (engine.LawPage, error)
	Embed(ctx context.Context, texts []string) (string, [][]float32, error)
}

// LawService держит нормы в базе в соответствии с движком: загружает при новой версии текста и досчитывает векторы,
// если раньше модель для них была недоступна.
type LawService struct {
	repo   Repository
	engine Engine
}

func NewLawService(repo Repository, eng Engine) *LawService {
	return &LawService{repo: repo, engine: eng}
}
