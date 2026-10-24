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
	query := `
	INSERT INTO pravkiapp.reviews (user_id, theirs_name, base_name, playbook, playbook_name, our_role, contract_type, side,
	                               counts, warnings, report_html, report_xlsx, changes, document, unified_docx)
	VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
	RETURNING ` + columns + `;`
	row := r.pool.QueryRow(ctx, query, rev.UserID, rev.TheirsName, rev.BaseName, rev.Playbook, rev.PlaybookName, rev.OurRole,
		rev.ContractType, rev.Side, counts, warnings, string(files.ReportHTML), files.ReportXLSX, changes, document, unified)
	out, err := scanReview(row)
	if err != nil {
		var ce *core_postgres_pool.ConstraintError
		if errors.As(err, &ce) && ce.Kind == core_postgres_pool.ErrForeignKeyViolation {
			return core_domain.ContractReview{}, fmt.Errorf("user %d not found: %w", rev.UserID, core_errors.ErrNotFound)
		}
		return core_domain.ContractReview{}, fmt.Errorf("insert review: %w", err)
	}
	return out, nil
}
