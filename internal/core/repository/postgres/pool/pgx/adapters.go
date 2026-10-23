package core_postgres_pgx

import (
	"errors"
	"fmt"

	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

type pgxRows struct {
	pgx.Rows
}

type pgxRow struct {
	pgx.Row
}

func (r pgxRow) Scan(dest ...any) error {
	err := r.Row.Scan(dest...)
	if err != nil {
		return mapErrors(err)
	}

	return nil
}

type pgxCommandTag struct {
	pgconn.CommandTag
}

func mapErrors(err error) error {
	const (
		pgxForeignKeyViolationErrCode = "23503"
		pgxUniqueViolationErrCode     = "23505"
	)

	if errors.Is(err, pgx.ErrNoRows) {
		return core_postgres_pool.ErrNoRows
	}

	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		if pgErr.Code == pgxUniqueViolationErrCode {
			return &core_postgres_pool.ConstraintError{
				Kind:       core_postgres_pool.ErrUniqueViolation,
				Constraint: pgErr.ConstraintName,
				Err:        err,
			}
		}
		if pgErr.Code == pgxForeignKeyViolationErrCode {
			return &core_postgres_pool.ConstraintError{
				Kind:       core_postgres_pool.ErrForeignKeyViolation,
				Constraint: pgErr.ConstraintName,
				Err:        err,
			}
		}
	}

	return fmt.Errorf("%v:%w", err, core_postgres_pool.ErrUnknown)
}
