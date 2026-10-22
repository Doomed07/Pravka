package auth_service

import (
	"context"
	"fmt"
	"runtime"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	"golang.org/x/crypto/bcrypt"
)

type AuthService struct {
	repo      AuthRepository
	cost      int
	ttl       time.Duration
	now       func() time.Time
	dummyHash []byte        // для выравнивания времени, когда пользователя нет
	sem       chan struct{} // не больше NumCPU одновременных bcrypt
}

type AuthRepository interface {
	CreateUser(ctx context.Context, user core_domain.User, passwordHash string) (core_domain.User, error)
	GetCredentialsByLogin(ctx context.Context, login string) (core_domain.Credentials, error)
	CreateSession(ctx context.Context, tokenHash []byte, userID int, expiresAt time.Time) error
	GetSession(ctx context.Context, tokenHash []byte) (core_domain.Session, core_domain.User, error)
	DeleteSession(ctx context.Context, tokenHash []byte) error
	DeleteExpiredSessions(ctx context.Context, now time.Time) error
}

func NewAuthService(repo AuthRepository, cost int, ttl time.Duration) (*AuthService, error) {
	if cost < bcrypt.MinCost || cost > bcrypt.MaxCost {
		return nil, fmt.Errorf("bcrypt cost %d out of range", cost)
	}
	if ttl <= 0 {
		return nil, fmt.Errorf("session ttl must be positive, got %s", ttl)
	}
	dummy, err := bcrypt.GenerateFromPassword([]byte("dummy-password"), cost)
	if err != nil {
		return nil, fmt.Errorf("generate dummy hash: %w", err)
	}
	return &AuthService{
		repo: repo, cost: cost, ttl: ttl, now: time.Now,
		dummyHash: dummy, sem: make(chan struct{}, runtime.NumCPU()),
	}, nil
}
