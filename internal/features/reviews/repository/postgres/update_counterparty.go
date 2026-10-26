package reviews_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

// RenameCounterparty меняет название и ИНН контрагента. Папка на диске не меняется: файлы уже лежат в ней.
// Занятое название — ErrConflict, чужой контрагент — ErrNotFound.
func (r *ReviewsRepository) RenameCounterparty(ctx context.Context, userID, id int, name, inn string) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	var updated int
	err := r.pool.QueryRow(ctx, `UPDATE pravkiapp.counterparties SET name = $3, inn = $4 WHERE id = $1 AND user_id = $2 RETURNING id;`,
		id, userID, name, inn).Scan(&updated)
	if err != nil {
		var ce *core_postgres_pool.ConstraintError
		switch {
		case errors.As(err, &ce) && ce.Kind == core_postgres_pool.ErrUniqueViolation:
			return fmt.Errorf("контрагент «%s» уже есть: %w", name, core_errors.ErrConflict)
		case errors.Is(err, core_postgres_pool.ErrNoRows):
			return fmt.Errorf("counterparty %d: %w", id, core_errors.ErrNotFound)
		}
		return fmt.Errorf("rename counterparty: %w", err)
	}
	return nil
}

// MoveProject переносит договор к другому контрагенту (оба свои). Папка договора на диске остаётся прежней.
func (r *ReviewsRepository) MoveProject(ctx context.Context, userID, projectID, counterpartyID int) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	tag, err := r.pool.Exec(ctx, `
	UPDATE pravkiapp.projects p SET counterparty_id = $3
	WHERE p.id = $1 AND p.user_id = $2
	  AND EXISTS (SELECT 1 FROM pravkiapp.counterparties c WHERE c.id = $3 AND c.user_id = $2);`, projectID, userID, counterpartyID)
	if err != nil {
		return fmt.Errorf("move project: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return fmt.Errorf("project %d or counterparty %d: %w", projectID, counterpartyID, core_errors.ErrNotFound)
	}
	return nil
}
