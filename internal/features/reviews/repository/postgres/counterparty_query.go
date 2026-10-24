package reviews_repository_postgres

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

// Контрагент с числом договоров и раундов и временем последнего раунда.
const counterpartyQuery = `
SELECT c.id, c.user_id, c.name, c.inn, c.dir, c.created_at,
       (SELECT count(*) FROM pravkiapp.projects p WHERE p.counterparty_id = c.id),
       (SELECT count(*) FROM pravkiapp.reviews r JOIN pravkiapp.projects p ON p.id = r.project_id WHERE p.counterparty_id = c.id),
       coalesce((SELECT max(r.created_at) FROM pravkiapp.reviews r JOIN pravkiapp.projects p ON p.id = r.project_id
                 WHERE p.counterparty_id = c.id), c.created_at)
FROM pravkiapp.counterparties c
WHERE c.user_id = $1`

func scanCounterparty(row interface{ Scan(dest ...any) error }, m *CounterpartyModel) error {
	return row.Scan(&m.ID, &m.UserID, &m.Name, &m.INN, &m.Dir, &m.CreatedAt, &m.Contracts, &m.Rounds, &m.LastAt)
}

func (r *ReviewsRepository) getCounterparty(ctx context.Context, userID, id int) (core_domain.CounterpartySummary, error) {
	var m CounterpartyModel
	if err := scanCounterparty(r.pool.QueryRow(ctx, counterpartyQuery+` AND c.id = $2;`, userID, id), &m); err != nil {
		if isNoRows(err) {
			return core_domain.CounterpartySummary{}, fmt.Errorf("counterparty %d: %w", id, core_errors.ErrNotFound)
		}
		return core_domain.CounterpartySummary{}, fmt.Errorf("select counterparty: %w", err)
	}
	return counterpartySummaryDomainFromModel(m), nil
}

// GetCounterparty — контрагент пользователя. Чужой неотличим от несуществующего (404).
func (r *ReviewsRepository) GetCounterparty(ctx context.Context, userID, id int) (core_domain.CounterpartySummary, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()
	return r.getCounterparty(ctx, userID, id)
}

// ListCounterparties — контрагенты пользователя, с недавними раундами — первыми.
func (r *ReviewsRepository) ListCounterparties(ctx context.Context, userID, limit int) ([]core_domain.CounterpartySummary, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	rows, err := r.pool.Query(ctx, counterpartyQuery+` ORDER BY 9 DESC, c.id DESC LIMIT $2;`, userID, limit)
	if err != nil {
		return nil, fmt.Errorf("select counterparties: %w", err)
	}
	defer rows.Close()
	out := []core_domain.CounterpartySummary{}
	for rows.Next() {
		var m CounterpartyModel
		if err := scanCounterparty(rows, &m); err != nil {
			return nil, fmt.Errorf("scan counterparty: %w", err)
		}
		out = append(out, counterpartySummaryDomainFromModel(m))
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate counterparties: %w", err)
	}
	return out, nil
}

// ListCounterpartyProjects — договоры контрагента, недавно менявшиеся — первыми.
func (r *ReviewsRepository) ListCounterpartyProjects(ctx context.Context, userID, counterpartyID int) ([]core_domain.ProjectSummary, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	rows, err := r.pool.Query(ctx, projectSummaryQuery+` AND p.counterparty_id = $2
	ORDER BY coalesce(l.created_at, p.created_at) DESC, p.id DESC;`, userID, counterpartyID)
	if err != nil {
		return nil, fmt.Errorf("select counterparty projects: %w", err)
	}
	defer rows.Close()
	out := []core_domain.ProjectSummary{}
	for rows.Next() {
		var m ProjectSummaryModel
		if err := scanProjectSummary(rows, &m); err != nil {
			return nil, fmt.Errorf("scan project: %w", err)
		}
		out = append(out, projectSummaryDomainFromModel(m))
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate projects: %w", err)
	}
	return out, nil
}
