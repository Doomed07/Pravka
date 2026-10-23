package core_postgres_pgx

import (
	"context"
	"fmt"
	"time"

	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
	"github.com/jackc/pgx/v5/pgxpool"
)

type ConnPool struct {
	*pgxpool.Pool
	opTimeout time.Duration
}

func NewConnPool(config Config, ctx context.Context) (*ConnPool, error) {
	connString := fmt.Sprintf(
		"postgres://%s:%s@%s:%s/%s?sslmode=disable",
		config.User,
		config.Pass,
		config.Host,
		config.Port,
		config.Database,
	)

	pgxconfig, err := pgxpool.ParseConfig(connString)
	if err != nil {
		return nil, fmt.Errorf("parse pgxconfig: %w", err)
	}

	pool, err := pgxpool.NewWithConfig(ctx, pgxconfig)
	if err != nil {
		return nil, fmt.Errorf("create pgxpool: %w", err)
	}

	if err := pool.Ping(ctx); err != nil {
		return nil, fmt.Errorf("ping pgxpool: %w", err)
	}

	return &ConnPool{
		Pool:      pool,
		opTimeout: config.Timeout,
	}, nil
}

func (p *ConnPool) Query(
	ctx context.Context,
	sql string,
	args ...any,
) (core_postgres_pool.Rows, error) {
	rows, err := p.Pool.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}

	return pgxRows{rows}, nil
}

func (p *ConnPool) QueryRow(
	ctx context.Context,
	sql string,
	args ...any) core_postgres_pool.Row {
	row := p.Pool.QueryRow(ctx, sql, args...)

	return pgxRow{row}
}

func (p *ConnPool) Exec(
	ctx context.Context,
	sql string,
	arguments ...any) (core_postgres_pool.CommandTag, error) {
	tag, err := p.Pool.Exec(ctx, sql, arguments...)
	if err != nil {
		return nil, err
	}
	return pgxCommandTag{tag}, nil
}

func (p *ConnPool) OpTimeout() time.Duration {
	return p.opTimeout
}
