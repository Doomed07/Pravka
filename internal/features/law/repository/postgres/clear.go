package law_repository_postgres

import (
	"context"
	"fmt"
)

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
