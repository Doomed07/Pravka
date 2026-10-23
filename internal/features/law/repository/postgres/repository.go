package law_repository_postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

// LawRepository — нормы закона в базе: пункты статей с поиском по словам и вектором.
type LawRepository struct {
	pool core_postgres_pool.Pool
}

func NewLawRepository(pool core_postgres_pool.Pool) *LawRepository {
	return &LawRepository{pool: pool}
}

// Meta — загруженная версия набора и модель векторов (” — без векторов). Пустая версия — ещё ничего не загружено.
func (r *LawRepository) Meta(ctx context.Context, code string) (version, model string, err error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	err = r.pool.QueryRow(ctx, `SELECT version, model FROM pravkiapp.law_meta WHERE code = $1;`, code).Scan(&version, &model)
	if errors.Is(err, core_postgres_pool.ErrNoRows) {
		return "", "", nil
	}
	if err != nil {
		return "", "", fmt.Errorf("select law meta: %w", err)
	}
	return version, model, nil
}

// Clear удаляет пункты и отметку о версии: загрузка начинается заново.
func (r *LawRepository) Clear(ctx context.Context, code string) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.pool.Exec(ctx, `DELETE FROM pravkiapp.law_meta WHERE code = $1;`, code); err != nil {
		return fmt.Errorf("delete law meta: %w", err)
	}
	if _, err := r.pool.Exec(ctx, `DELETE FROM pravkiapp.law_points WHERE code = $1;`, code); err != nil {
		return fmt.Errorf("delete law points: %w", err)
	}
	return nil
}

// vectorLiteral — вектор в записи pgvector: [0.1,0.2,…]. nil — NULL (без вектора).
func vectorLiteral(v []float32) *string {
	if v == nil {
		return nil
	}
	parts := make([]string, len(v))
	for i, x := range v {
		parts[i] = strconv.FormatFloat(float64(x), 'g', -1, 32)
	}
	s := "[" + strings.Join(parts, ",") + "]"
	return &s
}

// Insert добавляет пункты одним запросом; vectors — по одному на пункт или nil (без векторов).
func (r *LawRepository) Insert(ctx context.Context, points []core_domain.LawPoint, vectors [][]float32) error {
	if len(points) == 0 {
		return nil
	}
	if vectors != nil && len(vectors) != len(points) {
		return fmt.Errorf("векторов %d, пунктов %d", len(vectors), len(points))
	}
	type row struct {
		core_domain.LawPoint
		Embedding *string `json:"embedding"`
	}
	rows := make([]row, len(points))
	for i, p := range points {
		rows[i] = row{LawPoint: p}
		if vectors != nil {
			rows[i].Embedding = vectorLiteral(vectors[i])
		}
	}
	data, err := json.Marshal(rows)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	_, err = r.pool.Exec(ctx, `
	INSERT INTO pravkiapp.law_points (code, article, seq, point, title, section, chapter, paragraph, edited, text, embedding)
	SELECT code, article, seq, point, title, section, chapter, paragraph, edited, text, embedding::vector
	FROM jsonb_to_recordset($1::jsonb) AS x(code text, article text, seq int, point text, title text, section text,
	                                        chapter text, paragraph text, edited text, text text, embedding text);`, string(data))
	if err != nil {
		return fmt.Errorf("insert law points: %w", err)
	}
	return nil
}

// SetMeta отмечает, что набор загружен полностью: version и модель векторов.
func (r *LawRepository) SetMeta(ctx context.Context, code, version, model string) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	_, err := r.pool.Exec(ctx, `
	INSERT INTO pravkiapp.law_meta (code, version, model) VALUES ($1, $2, $3)
	ON CONFLICT (code) DO UPDATE SET version = EXCLUDED.version, model = EXCLUDED.model, loaded_at = NOW();`, code, version, model)
	if err != nil {
		return fmt.Errorf("save law meta: %w", err)
	}
	return nil
}
