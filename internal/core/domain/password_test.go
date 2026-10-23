package core_domain_test

import (
	"errors"
	"strings"
	"testing"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func TestValidatePassword(t *testing.T) {
	tests := []struct {
		name     string
		password string
		wantErr  bool
	}{
		{
			name:     "empty",
			password: "",
			wantErr:  true,
		},
		{
			name:     "too short",
			password: "Keks23%",
			wantErr:  true,
		},
		{
			name:     "too short (7)",
			password: strings.Repeat("a", 7),
			wantErr:  true,
		},
		{
			name:     "too long (73)",
			password: strings.Repeat("a", 73),
			wantErr:  true,
		},
		{
			name:     "space",
			password: " Kant123! ",
			wantErr:  true,
		},
		{
			name:     "space inside",
			password: "Kant 123!",
			wantErr:  true,
		},
		{
			name:     "cyrillic",
			password: "проверка234!",
			wantErr:  true,
		},
		{
			name:     "emoji",
			password: "Passw0rd😀",
			wantErr:  true,
		},
		{
			name:     "tab",
			password: "Pass\tword1",
			wantErr:  true,
		},
		{
			name:     "newline",
			password: "Pass\nword1",
			wantErr:  true,
		},
		{
			name:     "null byte",
			password: "Pass\x00word1",
			wantErr:  true,
		},
		{
			name:     "del character",
			password: "Pass\x7Fword1",
			wantErr:  true,
		},
		{
			name:     "non-breaking space",
			password: "Pass word1",
			wantErr:  true,
		},
		{
			name:     "valid 8",
			password: "Kant123!",
			wantErr:  false,
		},
		{
			name:     "valid 72",
			password: strings.Repeat("a", 72),
			wantErr:  false,
		},
		{
			name:     "lowest allowed char",
			password: strings.Repeat("!", 8),
			wantErr:  false,
		},
		{
			name:     "highest allowed char",
			password: strings.Repeat("~", 8),
			wantErr:  false,
		},
		{
			name:     "all kinds of symbols",
			password: "Aa1!@#$%^&*()-_=+[]{};:'\",.<>/?\\|`~",
			wantErr:  false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotErr := core_domain.ValidatePassword(tt.password)

			if tt.wantErr {
				if gotErr == nil {
					t.Fatal("ValidatePassword() succeeded unexpectedly")
				}
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("ValidatePassword() err = %v, want ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Errorf("ValidatePassword() failed: %v", gotErr)
			}
		})
	}
}
