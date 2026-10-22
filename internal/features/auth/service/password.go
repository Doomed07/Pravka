package auth_service

import (
	"context"
	"fmt"

	"golang.org/x/crypto/bcrypt"
)

func (s *AuthService) acquire(ctx context.Context) (func(), error) {
	select {
	case s.sem <- struct{}{}:
		return func() { <-s.sem }, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func (s *AuthService) hashPassword(ctx context.Context, password string) (string, error) {
	release, err := s.acquire(ctx)
	if err != nil {
		return "", err
	}
	defer release()
	hash, err := bcrypt.GenerateFromPassword([]byte(password), s.cost)
	if err != nil {
		return "", fmt.Errorf("generate hash: %w", err)
	}
	return string(hash), nil
}

// comparePassword: nil — совпало, bcrypt.ErrMismatchedHashAndPassword — нет.
func (s *AuthService) comparePassword(ctx context.Context, hash []byte, password string) error {
	release, err := s.acquire(ctx)
	if err != nil {
		return err
	}
	defer release()
	return bcrypt.CompareHashAndPassword(hash, []byte(password))
}
