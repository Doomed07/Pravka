package law_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

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
