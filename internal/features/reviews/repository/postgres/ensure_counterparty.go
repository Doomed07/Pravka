package reviews_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

// EnsureCounterparty — контрагент для нового договора: по номеру (id > 0, должен быть свой) или по названию без учёта
// регистра: нашли — взяли, нет — создали. ИНН дописывается, если у найденного он ещё не указан.
func (r *ReviewsRepository) EnsureCounterparty(ctx context.Context, userID, id int, name, inn string) (core_domain.Counterparty, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if id > 0 {
		c, err := r.getCounterparty(ctx, userID, id)
		if err != nil {
			return core_domain.Counterparty{}, err
		}
		return c.Counterparty, nil
	}
	var c core_domain.Counterparty
	err := r.pool.QueryRow(ctx, `
	WITH found AS (
	    UPDATE pravkiapp.counterparties SET inn = CASE WHEN inn = '' THEN $3 ELSE inn END
	    WHERE user_id = $1 AND lower(name) = lower($2)
	    RETURNING id, user_id, name, inn, dir, created_at
	), made AS (
	    INSERT INTO pravkiapp.counterparties (user_id, name, inn) SELECT $1, $2, $3 WHERE NOT EXISTS (SELECT 1 FROM found)
	    RETURNING id, user_id, name, inn, dir, created_at
	)
	SELECT id, user_id, name, inn, dir, created_at FROM found UNION ALL SELECT id, user_id, name, inn, dir, created_at FROM made;`,
		userID, name, inn).Scan(&c.ID, &c.UserID, &c.Name, &c.INN, &c.Dir, &c.CreatedAt)
	if err != nil {
		return core_domain.Counterparty{}, fmt.Errorf("ensure counterparty: %w", err)
	}
	return c, nil
}

// AssignCounterpartyDir задаёт папку контрагента, если её ещё нет: base, а при совпадении с чужой папкой (без учёта
// регистра: на Mac «Ромашка» и «ромашка» — одна папка) — «base 2», «base 3»… Возвращает итоговую папку.
func (r *ReviewsRepository) AssignCounterpartyDir(ctx context.Context, userID, id int, base string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	c, err := r.getCounterparty(ctx, userID, id)
	if err != nil {
		return "", err
	}
	if c.Dir != "" {
		return c.Dir, nil
	}
	dir := base
	for n := 2; ; n++ {
		var taken bool
		if err := r.pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM pravkiapp.counterparties WHERE lower(dir) = lower($1));`,
			dir).Scan(&taken); err != nil {
			return "", fmt.Errorf("check counterparty dir: %w", err)
		}
		if !taken {
			break
		}
		dir = fmt.Sprintf("%s %d", base, n)
	}
	if _, err := r.pool.Exec(ctx, `UPDATE pravkiapp.counterparties SET dir = $3 WHERE id = $1 AND user_id = $2;`, id, userID, dir); err != nil {
		return "", fmt.Errorf("assign counterparty dir: %w", err)
	}
	return dir, nil
}

// ProjectDirTaken — занят ли путь папки договора (без учёта регистра).
func (r *ReviewsRepository) ProjectDirTaken(ctx context.Context, dir string) (bool, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	var taken bool
	if err := r.pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM pravkiapp.projects WHERE lower(dir) = lower($1));`, dir).Scan(&taken); err != nil {
		return false, fmt.Errorf("check project dir: %w", err)
	}
	return taken, nil
}

func isNoRows(err error) bool { return errors.Is(err, core_postgres_pool.ErrNoRows) }
