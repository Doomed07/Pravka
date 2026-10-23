package auth_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

const (
	usernameConstraint = "users_username_lower_uidx"
	emailConstraint    = "users_email_key"
)

func (r *AuthRepository) CreateUser(
	ctx context.Context,
	user core_domain.User,
	passwordHash string,
) (core_domain.User, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	query := `
	INSERT INTO pravkiapp.users (username, email, password_hash)
	VALUES ($1, $2, $3)
	RETURNING id, version, username, email, created_at;
	`

	row := r.pool.QueryRow(ctx, query, user.Username, user.Email, passwordHash)

	var userModel UserModel
	err := row.Scan(
		&userModel.ID,
		&userModel.Version,
		&userModel.Username,
		&userModel.Email,
		&userModel.CreatedAt,
	)
	if err != nil {
		var ce *core_postgres_pool.ConstraintError
		if errors.As(err, &ce) && ce.Kind == core_postgres_pool.ErrUniqueViolation {
			switch ce.Constraint {

			case usernameConstraint:
				return core_domain.User{}, fmt.Errorf(
					"username %q is already taken: %w",
					user.Username, core_errors.ErrConflict)

			case emailConstraint:
				return core_domain.User{}, fmt.Errorf(
					"email %q is already registered: %w",
					user.Email, core_errors.ErrConflict)
			}
		}
		return core_domain.User{}, fmt.Errorf("scan query row: %w", err)
	}

	userDomain := core_domain.NewUser(
		userModel.ID,
		userModel.Version,
		userModel.Username,
		userModel.Email,
		userModel.CreatedAt,
	)

	return userDomain, nil

}
