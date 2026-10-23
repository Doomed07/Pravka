package auth_repository_postgres

import (
	"context"
	"fmt"
	"time"
)

func (r *AuthRepository) DeleteExpiredSessions(ctx context.Context, now time.Time) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	query := `
	DELETE FROM pravkiapp.sessions
	WHERE expires_at <= $1
	`

	_, err := r.pool.Exec(ctx, query, now)
	if err != nil {
		return fmt.Errorf("exec query: %w", err)
	}

	return nil
}
