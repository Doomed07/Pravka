package auth_service

import (
	"context"
	"fmt"
	"strings"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
)

func (s *AuthService) Register(
	ctx context.Context,
	username, email, password string,
) (core_domain.User, string, error) {
	user := core_domain.NewUserUninitialized(username, email)
	if err := user.Validate(); err != nil {
		return core_domain.User{}, "", fmt.Errorf("validate user: %w", err)
	}

	if err := core_domain.ValidatePassword(password); err != nil {
		return core_domain.User{}, "", fmt.Errorf("validate password: %w", err)
	}

	if strings.EqualFold(password, user.Username) {
		return core_domain.User{}, "",
			fmt.Errorf("password must not equal username: %w",
				core_errors.ErrInvalidArgument)
	}

	hash, err := s.hashPassword(ctx, password)
	if err != nil {
		return core_domain.User{}, "", fmt.Errorf("hash password: %w", err)
	}
	created, err := s.repo.CreateUser(ctx, user, hash)
	if err != nil {
		return core_domain.User{}, "", fmt.Errorf("create user: %w", err)
	}
	token, err := s.startSession(ctx, created.ID)
	if err != nil {
		return core_domain.User{}, "", err
	}

	core_metrics.Registrations.Inc()
	return created, token, nil
}
