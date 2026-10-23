package auth_repository_postgres

import (
	"context"
	"fmt"
	"time"
)

func (r *AuthRepository) CreateSession(ctx context.Context, tokenHash []byte, userID int, expiresAt time.Time) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	query := `
	INSERT INTO pravkiapp.sessions (token_hash, expires_at, user_id)
	VALUES ($1, $2, $3);
	`

	_, err := r.pool.Exec(ctx, query, tokenHash, expiresAt, userID)
	if err != nil {
		return fmt.Errorf("exec query: %w", err)
	}

	return nil

}
