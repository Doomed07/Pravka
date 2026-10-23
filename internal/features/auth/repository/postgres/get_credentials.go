package auth_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

func (r *AuthRepository) GetCredentialsByLogin(ctx context.Context, login string) (core_domain.Credentials, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	query := `
	SELECT id, version, username, email, created_at, password_hash
	FROM pravkiapp.users
	WHERE email = lower($1) OR lower(username) = lower($1);
	`

	row := r.pool.QueryRow(ctx, query, login)

	var auth CredentialsModel
	err := row.Scan(
		&auth.User.ID,
		&auth.User.Version,
		&auth.User.Username,
		&auth.User.Email,
		&auth.User.CreatedAt,
		&auth.PasswordHash,
	)
	if err != nil {
		if errors.Is(err, core_postgres_pool.ErrNoRows) {
			return core_domain.Credentials{}, fmt.Errorf(
				"user with login: %s not found. Error: %w",
				login, core_errors.ErrNotFound)
		}

		return core_domain.Credentials{}, fmt.Errorf("failed to scan row: %w", err)
	}

	credentialsDomain := core_domain.NewCredentials(
		core_domain.NewUser(
			auth.User.ID,
			auth.User.Version,
			auth.User.Username,
			auth.User.Email,
			auth.User.CreatedAt,
		),
		auth.PasswordHash,
	)

	return credentialsDomain, nil
}
