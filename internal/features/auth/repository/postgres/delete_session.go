package auth_repository_postgres

import (
	"context"
	"fmt"
)

func (r *AuthRepository) DeleteSession(ctx context.Context, tokenHash []byte) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	query := `
	DELETE FROM pravkiapp.sessions
	WHERE token_hash = $1
	`

	_, err := r.pool.Exec(ctx, query, tokenHash)
	if err != nil {
		return fmt.Errorf("exec query: %w", err)
	}

	return nil
}
