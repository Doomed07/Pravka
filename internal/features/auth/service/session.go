package auth_service

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
)

func hashToken(token string) []byte {
	sum := sha256.Sum256([]byte(token))
	return sum[:]
}

func newToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("read random: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

func (s *AuthService) startSession(ctx context.Context, userID int) (string, error) {
	token, err := newToken()
	if err != nil {
		return "", err
	}
	if err := s.repo.CreateSession(ctx, hashToken(token), userID, s.now().Add(s.ttl)); err != nil {
		return "", fmt.Errorf("create session: %w", err)
	}
	return token, nil // клиенту уходит token, в БД лежит только sha256(token)
}
