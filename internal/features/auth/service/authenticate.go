package auth_service

import (
	"context"
	"errors"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func (s *AuthService) Authenticate(ctx context.Context, token string) (core_domain.User, error) {
	if token == "" {
		return core_domain.User{}, fmt.Errorf("no session token: %w", core_errors.ErrUnauthorized)
	}
	session, user, err := s.repo.GetSession(ctx, hashToken(token))
	if err != nil {
		if errors.Is(err, core_errors.ErrNotFound) {
			return core_domain.User{}, fmt.Errorf("session not found: %w", core_errors.ErrUnauthorized)
		}
		return core_domain.User{}, fmt.Errorf("get session: %w", err)
	}
	if !s.now().Before(session.ExpiresAt) { // истекла, когда now >= expires_at
		return core_domain.User{}, fmt.Errorf("session expired: %w", core_errors.ErrUnauthorized)
	}
	return user, nil
}
