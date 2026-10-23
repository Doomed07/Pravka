package core_http_response

import (
	"errors"
	"fmt"
	"net/http"
	"testing"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func TestStatusFromError(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want int
	}{
		{name: "conflict", err: core_errors.ErrConflict, want: http.StatusConflict},
		{name: "invalid argument", err: core_errors.ErrInvalidArgument, want: http.StatusBadRequest},
		{name: "not found", err: core_errors.ErrNotFound, want: http.StatusNotFound},
		{name: "unauthorized", err: core_errors.ErrUnauthorized, want: http.StatusUnauthorized},
		{name: "forbidden", err: core_errors.ErrForbidden, want: http.StatusForbidden},
		{
			name: "wrapped twice",
			err:  fmt.Errorf("service: %w", fmt.Errorf("repo: %w", core_errors.ErrNotFound)),
			want: http.StatusNotFound,
		},
		{
			name: "conflict wins over invalid argument",
			err:  fmt.Errorf("%w: %w", core_errors.ErrInvalidArgument, core_errors.ErrConflict),
			want: http.StatusConflict,
		},
		{name: "unknown error", err: errors.New("db is down"), want: http.StatusInternalServerError},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := StatusFromError(tt.err); got != tt.want {
				t.Errorf("StatusFromError() = %d, want %d", got, tt.want)
			}
		})
	}
}
