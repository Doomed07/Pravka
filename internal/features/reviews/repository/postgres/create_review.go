package reviews_repository_postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

func (r *ReviewsRepository) CreateReview(ctx context.Context, rev core_domain.ContractReview, files core_domain.ReviewFiles) (core_domain.ContractReview, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	counts, err := json.Marshal(rev.Counts)
	if err != nil {
		return core_domain.ContractReview{}, err
	}
	if rev.Warnings == nil {
		rev.Warnings = []string{}
	}
	warnings, err := json.Marshal(rev.Warnings)
	if err != nil {
		return core_domain.ContractReview{}, err
	}
	changes := files.Changes
	if len(changes) == 0 {
		changes = []byte("[]")
	}
	document := files.Document
	if len(document) == 0 {
		document = []byte("[]")
	}
	var unified []byte // NULL, если движок не прислал единую версию
	if len(files.Unified) > 0 {
		unified = files.Unified
	}
	// Новый договор (ProjectID == 0) создаётся тем же запросом: нет разбора без проекта и проекта без разбора.
	query := `
	WITH new_project AS (
	    INSERT INTO pravkiapp.projects (user_id, name) SELECT $1, coalesce(nullif(btrim($16::text), ''), 'Договор') WHERE $17::int = 0 RETURNING id
	)
	INSERT INTO pravkiapp.reviews (user_id, theirs_name, base_name, playbook, playbook_name, our_role, contract_type, side,
	                               counts, warnings, report_html, report_xlsx, changes, document, unified_docx, project_id)
	VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
	        coalesce(nullif($17::int, 0), (SELECT id FROM new_project)))
	RETURNING id;`
	row := r.pool.QueryRow(ctx, query, rev.UserID, rev.TheirsName, rev.BaseName, rev.Playbook, rev.PlaybookName, rev.OurRole,
		rev.ContractType, rev.Side, counts, warnings, string(files.ReportHTML), files.ReportXLSX, changes, document, unified,
		rev.ProjectName, rev.ProjectID)
	var id int
	if err := row.Scan(&id); err != nil {
		var ce *core_postgres_pool.ConstraintError
		if errors.As(err, &ce) && ce.Kind == core_postgres_pool.ErrForeignKeyViolation {
			return core_domain.ContractReview{}, fmt.Errorf("user %d not found: %w", rev.UserID, core_errors.ErrNotFound)
		}
		return core_domain.ContractReview{}, fmt.Errorf("insert review: %w", err)
	}
	// название договора и номер раунда читаем отдельным запросом: новый договор из того же запроса в RETURNING не виден
	out, err := r.GetReview(ctx, rev.UserID, id)
	if err != nil {
		return core_domain.ContractReview{}, fmt.Errorf("select created review: %w", err)
	}
	return out, nil
}
