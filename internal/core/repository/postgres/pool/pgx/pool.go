package core_postgres_pgx

import (
	"context"
	"fmt"
	"time"

	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
	"github.com/jackc/pgx/v5/pgxpool"
)

// При запуске база может быть ещё не готова (после перезагрузки компьютера или «make up»): ждём её, а не падаем сразу.
var (
	StartWait       = 60 * time.Second // сколько ждать базу при запуске
	StartRetryEvery = 2 * time.Second
	// OnStartRetry вызывается после каждой неудачной попытки: основной пакет пишет в журнал «жду базу».
	OnStartRetry func(attempt int, err error)
)

// pingWithRetry пробует ping, пока не получится, не кончится время wait или не отменён ctx. Возвращает последнюю ошибку.
func pingWithRetry(ctx context.Context, ping func(context.Context) error, wait, every time.Duration, onRetry func(int, error)) error {
	deadline := time.Now().Add(wait)
	for attempt := 1; ; attempt++ {
		err := ping(ctx)
		if err == nil {
			return nil
		}
		if ctx.Err() != nil || !time.Now().Add(every).Before(deadline) {
			return err
		}
		if onRetry != nil {
			onRetry(attempt, err)
		}
		select {
		case <-ctx.Done():
			return err
		case <-time.After(every):
		}
	}
}

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

	if err := pingWithRetry(ctx, pool.Ping, StartWait, StartRetryEvery, OnStartRetry); err != nil {
		pool.Close()
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
