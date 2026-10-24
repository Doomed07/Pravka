package core_postgres_pgx

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestPingWithRetry(t *testing.T) {
	boom := errors.New("connection refused")
	t.Run("база поднимается не сразу", func(t *testing.T) {
		calls, retries := 0, 0
		err := pingWithRetry(context.Background(), func(context.Context) error {
			calls++
			if calls < 3 {
				return boom
			}
			return nil
		}, time.Second, time.Millisecond, func(int, error) { retries++ })
		if err != nil || calls != 3 || retries != 2 {
			t.Fatalf("err = %v, calls = %d, retries = %d; want nil, 3, 2", err, calls, retries)
		}
	})
	t.Run("база уже готова: без ожидания", func(t *testing.T) {
		calls := 0
		if err := pingWithRetry(context.Background(), func(context.Context) error { calls++; return nil }, time.Second, time.Hour, nil); err != nil || calls != 1 {
			t.Fatalf("err = %v, calls = %d", err, calls)
		}
	})
	t.Run("время вышло: последняя ошибка", func(t *testing.T) {
		calls := 0
		err := pingWithRetry(context.Background(), func(context.Context) error { calls++; return boom }, 30*time.Millisecond, 10*time.Millisecond, nil)
		if !errors.Is(err, boom) || calls < 2 || calls > 4 {
			t.Fatalf("err = %v, calls = %d", err, calls)
		}
	})
	t.Run("остановка во время ожидания", func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		calls := 0
		start := time.Now()
		err := pingWithRetry(ctx, func(context.Context) error {
			calls++
			cancel()
			return boom
		}, time.Hour, time.Hour, nil)
		if !errors.Is(err, boom) || calls != 1 || time.Since(start) > time.Second {
			t.Fatalf("err = %v, calls = %d, waited %v", err, calls, time.Since(start))
		}
	})
	t.Run("не дожидаемся следующей попытки за пределом срока", func(t *testing.T) {
		calls := 0
		start := time.Now()
		err := pingWithRetry(context.Background(), func(context.Context) error { calls++; return boom }, 50*time.Millisecond, time.Hour, nil)
		if !errors.Is(err, boom) || calls != 1 || time.Since(start) > time.Second {
			t.Fatalf("err = %v, calls = %d, waited %v", err, calls, time.Since(start))
		}
	})
}
