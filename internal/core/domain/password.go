package core_domain

import (
	"fmt"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

const (
	MinPasswordLen = 8
	MaxPasswordLen = 72
)

func ValidatePassword(password string) error {
	n := len(password)
	if n < MinPasswordLen || n > MaxPasswordLen {
		return fmt.Errorf("invalid 'password' len: %d bytes, want %d..%d: %w",
			n, MinPasswordLen, MaxPasswordLen, core_errors.ErrInvalidArgument)
	}
	for i := 0; i < len(password); i++ {
		if c := password[i]; c < 0x21 || c > 0x7E {
			return fmt.Errorf("invalid 'password': only latin letters, digits and symbols without spaces are allowed: %w",
				core_errors.ErrInvalidArgument)
		}
	}
	return nil
}
