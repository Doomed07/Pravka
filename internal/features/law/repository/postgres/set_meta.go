package law_repository_postgres

import (
	"context"
	"fmt"
)

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
