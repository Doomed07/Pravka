package core_domain

import "time"

// Credentials — пользователь вместе с хешем пароля. Живёт только внутри auth.
type Credentials struct {
	User         User
	PasswordHash string
}

func NewCredentials(user User, pass string) Credentials {
	return Credentials{
		User:         user,
		PasswordHash: pass,
	}
}

type Session struct {
	UserID    int
	ExpiresAt time.Time
}

func NewSession(id int, exp time.Time) Session {
	return Session{
		UserID:    id,
		ExpiresAt: exp,
	}
}
