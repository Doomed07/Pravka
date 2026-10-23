package auth_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

func (r *AuthRepository) GetSession(ctx context.Context, tokenHash []byte) (core_domain.Session, core_domain.User, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	query := `
	SELECT s.expires_at, s.user_id, u.id, u.version,
	u.username, u.email, u.created_at
	FROM pravkiapp.sessions s
	JOIN pravkiapp.users u ON u.id = s.user_id
	WHERE s.token_hash = $1;
	`

	row := r.pool.QueryRow(ctx, query, tokenHash)

	var s SessionModel
	var u UserModel
	err := row.Scan(
		&s.ExpiresAt,
		&s.UserID,
		&u.ID,
		&u.Version,
		&u.Username,
		&u.Email,
		&u.CreatedAt,
	)
	if err != nil {
		if errors.Is(err, core_postgres_pool.ErrNoRows) {
			return core_domain.Session{}, core_domain.User{},
				fmt.Errorf("session not found: %w", core_errors.ErrNotFound)
		}

		return core_domain.Session{}, core_domain.User{},
			fmt.Errorf("failed to scan row: %w", err)
	}

	sessionDomain := core_domain.NewSession(s.UserID, s.ExpiresAt)
	userDomain := core_domain.NewUser(
		u.ID,
		u.Version,
		u.Username,
		u.Email,
		u.CreatedAt,
	)

	return sessionDomain, userDomain, nil
}
