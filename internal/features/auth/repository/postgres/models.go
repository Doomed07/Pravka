package auth_repository_postgres

import (
	"time"
)

type UserModel struct {
	ID        int
	Version   int
	Username  string
	Email     string
	CreatedAt time.Time
}

type CredentialsModel struct {
	User         UserModel
	PasswordHash string
}

type SessionModel struct {
	UserID    int
	ExpiresAt time.Time
}
