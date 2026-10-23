package core_domain

import (
	"fmt"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

var (
	reUsername = regexp.MustCompile(`^[A-Za-z0-9_]+$`)
	reEmail    = regexp.MustCompile(`^[a-z0-9._+-]+@([a-z0-9-]+\.)+[a-z]{2,}$`)
)

type User struct {
	ID      int
	Version int

	Username  string
	Email     string
	CreatedAt time.Time
}

func NewUser(
	id, version int,
	username, email string,
	createdAt time.Time,
) User {
	return User{
		ID:        id,
		Version:   version,
		Username:  username,
		Email:     email,
		CreatedAt: createdAt,
	}

}

func NewUserUninitialized(
	username, email string,
) User {
	return NewUser(
		UninitializedID,
		UninitializedVersion,
		normalizeUsername(username),
		normalizeEmail(email),
		time.Time{},
	)
}

func normalizeUsername(username string) string {
	return strings.TrimSpace(username)
}

func normalizeEmail(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}

func (u *User) Validate() error {
	if err := u.ValidateUsername(); err != nil {
		return err
	}

	return u.ValidateEmail()
}

func (u *User) ValidateUsername() error {
	usernameLen := utf8.RuneCountInString(u.Username)
	if usernameLen < 3 || usernameLen > 30 {
		return fmt.Errorf(
			"invalid 'username' len: %d, error: %w",
			usernameLen, core_errors.ErrInvalidArgument)
	}

	if !reUsername.MatchString(u.Username) {
		return fmt.Errorf("invalid 'username' format: %w",
			core_errors.ErrInvalidArgument)
	}

	return nil
}

func (u *User) ValidateEmail() error {
	emailLen := utf8.RuneCountInString(u.Email)
	if emailLen > 254 {
		return fmt.Errorf(
			"invalid 'email' len: %d, error: %w",
			emailLen, core_errors.ErrInvalidArgument)
	}

	if !reEmail.MatchString(u.Email) {
		return fmt.Errorf("invalid 'email' format: %w",
			core_errors.ErrInvalidArgument)
	}
	return nil
}

type UserPatch struct {
	Username Nullable[string]
	Email    Nullable[string]
}

func NewUserPatch(username Nullable[string], email Nullable[string]) UserPatch {
	return UserPatch{
		Username: username,
		Email:    email,
	}
}

func (p *UserPatch) Validate() error {
	if p.Username.Set && p.Username.Value == nil {
		return fmt.Errorf("'username' can't be patched to NULL: %w",
			core_errors.ErrInvalidArgument)
	}

	if p.Email.Set && p.Email.Value == nil {
		return fmt.Errorf("'email' can't be patched to NULL: %w",
			core_errors.ErrInvalidArgument)
	}

	return nil
}

func (u *User) ApplyPatch(patch UserPatch) error {
	if err := patch.Validate(); err != nil {
		return fmt.Errorf("validate user patch: %w", err)
	}

	temp := *u

	if patch.Username.Set {
		temp.Username = normalizeUsername(*patch.Username.Value)
	}

	if patch.Email.Set {
		temp.Email = normalizeEmail(*patch.Email.Value)
	}

	if err := temp.Validate(); err != nil {
		return fmt.Errorf("validate patched user: %w", err)
	}

	*u = temp

	return nil
}
