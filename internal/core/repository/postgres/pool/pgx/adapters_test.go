package core_postgres_pgx

import (
	"errors"
	"fmt"
	"strings"
	"testing"

	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

func Test_mapErrors(t *testing.T) {
	uniqueErr := &pgconn.PgError{
		Code:           "23505",
		Message:        `duplicate key value violates unique constraint "users_email_key"`,
		ConstraintName: "users_email_key",
	}
	fkErr := &pgconn.PgError{
		Code:           "23503",
		Message:        `insert or update on table "bookshelf" violates foreign key constraint "bookshelf_book_id_fkey"`,
		ConstraintName: "bookshelf_book_id_fkey",
	}
	notNullErr := &pgconn.PgError{Code: "23502", Message: "null value in column violates not-null constraint"}

	tests := []struct {
		name           string
		err            error
		want           error  // ровно одна из sentinel-ошибок пула
		wantConstraint string // "" — ConstraintError быть не должно
		wantInText     string // что должно остаться в тексте для логов ("" — не проверяем)
	}{
		{
			name: "no rows",
			err:  pgx.ErrNoRows,
			want: core_postgres_pool.ErrNoRows,
		},
		{
			name: "no rows wrapped",
			err:  fmt.Errorf("query: %w", pgx.ErrNoRows),
			want: core_postgres_pool.ErrNoRows,
		},
		{
			name:           "unique violation",
			err:            uniqueErr,
			want:           core_postgres_pool.ErrUniqueViolation,
			wantConstraint: "users_email_key",
			wantInText:     "duplicate key",
		},
		{
			name:           "unique violation wrapped",
			err:            fmt.Errorf("scan: %w", uniqueErr),
			want:           core_postgres_pool.ErrUniqueViolation,
			wantConstraint: "users_email_key",
		},
		{
			name:           "foreign key violation",
			err:            fkErr,
			want:           core_postgres_pool.ErrForeignKeyViolation,
			wantConstraint: "bookshelf_book_id_fkey",
			wantInText:     "foreign key",
		},
		{
			name:       "other postgres error",
			err:        notNullErr,
			want:       core_postgres_pool.ErrUnknown,
			wantInText: "not-null",
		},
		{
			name:       "non-postgres error",
			err:        errors.New("connection reset"),
			want:       core_postgres_pool.ErrUnknown,
			wantInText: "connection reset",
		},
	}

	all := []error{
		core_postgres_pool.ErrNoRows,
		core_postgres_pool.ErrUniqueViolation,
		core_postgres_pool.ErrForeignKeyViolation,
		core_postgres_pool.ErrUnknown,
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := mapErrors(tt.err)
			if got == nil {
				t.Fatal("mapErrors() = nil, want error")
			}

			// совпадает ровно одна sentinel-ошибка: ни меньше, ни больше
			for _, sentinel := range all {
				if is := errors.Is(got, sentinel); is != (sentinel == tt.want) {
					t.Errorf("errors.Is(got, %v) = %v, want %v", sentinel, is, sentinel == tt.want)
				}
			}

			var ce *core_postgres_pool.ConstraintError
			hasConstraint := errors.As(got, &ce)
			if tt.wantConstraint == "" {
				if hasConstraint {
					t.Errorf("got ConstraintError %+v, want none", ce)
				}
			} else {
				if !hasConstraint {
					t.Fatalf("errors.As(ConstraintError) = false, want true; got = %v", got)
				}
				if ce.Constraint != tt.wantConstraint {
					t.Errorf("Constraint = %q, want %q", ce.Constraint, tt.wantConstraint)
				}
			}

			if tt.wantInText != "" && !strings.Contains(got.Error(), tt.wantInText) {
				t.Errorf("Error() = %q, want it to contain %q", got.Error(), tt.wantInText)
			}
		})
	}
}
