package reviews_repository_postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

type ReviewsRepository struct {
	pool core_postgres_pool.Pool
}

func NewReviewsRepository(pool core_postgres_pool.Pool) *ReviewsRepository {
	return &ReviewsRepository{pool: pool}
}

const columns = `id, user_id, created_at, theirs_name, base_name, playbook, playbook_name, our_role, side, counts, warnings`

func scanReview(row core_postgres_pool.Row) (core_domain.ContractReview, error) {
	var (
		r                core_domain.ContractReview
		created          time.Time
		counts, warnings []byte
	)
	if err := row.Scan(&r.ID, &r.UserID, &created, &r.TheirsName, &r.BaseName, &r.Playbook, &r.PlaybookName,
		&r.OurRole, &r.Side, &counts, &warnings); err != nil {
		return core_domain.ContractReview{}, err
	}
	r.CreatedAt = created
	if err := json.Unmarshal(counts, &r.Counts); err != nil {
		return core_domain.ContractReview{}, fmt.Errorf("decode counts: %w", err)
	}
	if err := json.Unmarshal(warnings, &r.Warnings); err != nil {
		return core_domain.ContractReview{}, fmt.Errorf("decode warnings: %w", err)
	}
	return r, nil
}

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
	INSERT INTO pravkiapp.reviews (user_id, theirs_name, base_name, playbook, playbook_name, our_role, side, counts, warnings,
	                               report_html, report_xlsx, changes, document, unified_docx)
	VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
	RETURNING ` + columns + `;`
	row := r.pool.QueryRow(ctx, query, rev.UserID, rev.TheirsName, rev.BaseName, rev.Playbook, rev.PlaybookName, rev.OurRole,
		rev.Side, counts, warnings, string(files.ReportHTML), files.ReportXLSX, changes, document, unified)
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

func (r *ReviewsRepository) ListReviews(ctx context.Context, userID, limit, offset int) ([]core_domain.ContractReview, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	rows, err := r.pool.Query(ctx, `SELECT `+columns+` FROM pravkiapp.reviews WHERE user_id = $1
	ORDER BY created_at DESC, id DESC LIMIT $2 OFFSET $3;`, userID, limit, offset)
	if err != nil {
		return nil, fmt.Errorf("select reviews: %w", err)
	}
	defer rows.Close()
	out := []core_domain.ContractReview{}
	for rows.Next() {
		rev, err := scanReview(rows)
		if err != nil {
			return nil, fmt.Errorf("scan review: %w", err)
		}
		out = append(out, rev)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate reviews: %w", err)
	}
	return out, nil
}

// GetReview — разбор пользователя. Чужой разбор неотличим от несуществующего (404), чтобы не раскрывать id.
func (r *ReviewsRepository) GetReview(ctx context.Context, userID, id int) (core_domain.ContractReview, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	row := r.pool.QueryRow(ctx, `SELECT `+columns+` FROM pravkiapp.reviews WHERE id = $1 AND user_id = $2;`, id, userID)
	rev, err := scanReview(row)
	if err != nil {
		if errors.Is(err, core_postgres_pool.ErrNoRows) {
			return core_domain.ContractReview{}, fmt.Errorf("review %d: %w", id, core_errors.ErrNotFound)
		}
		return core_domain.ContractReview{}, fmt.Errorf("select review: %w", err)
	}
	return rev, nil
}

// GetFile отдаёт одну из тяжёлых частей разбора: "html", "xlsx", "changes", "document" или "docx".
// У разборов, сделанных до появления единой версии, "docx" нет: ErrNotFound.
func (r *ReviewsRepository) GetFile(ctx context.Context, userID, id int, kind string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	column := map[string]string{"html": "convert_to(report_html, 'UTF8')", "xlsx": "report_xlsx",
		"changes": "convert_to(changes::text, 'UTF8')", "document": "convert_to(document::text, 'UTF8')",
		"docx": "unified_docx"}[kind]
	if column == "" {
		return nil, fmt.Errorf("unknown file kind %q: %w", kind, core_errors.ErrInvalidArgument)
	}
	var data []byte
	err := r.pool.QueryRow(ctx, `SELECT `+column+` FROM pravkiapp.reviews WHERE id = $1 AND user_id = $2;`, id, userID).Scan(&data)
	if err != nil {
		if errors.Is(err, core_postgres_pool.ErrNoRows) {
			return nil, fmt.Errorf("review %d: %w", id, core_errors.ErrNotFound)
		}
		return nil, fmt.Errorf("select review file: %w", err)
	}
	if data == nil {
		return nil, fmt.Errorf("review %d: no %s: %w", id, kind, core_errors.ErrNotFound)
	}
	return data, nil
}

func (r *ReviewsRepository) DeleteReview(ctx context.Context, userID, id int) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	tag, err := r.pool.Exec(ctx, `DELETE FROM pravkiapp.reviews WHERE id = $1 AND user_id = $2;`, id, userID)
	if err != nil {
		return fmt.Errorf("delete review: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return fmt.Errorf("review %d: %w", id, core_errors.ErrNotFound)
	}
	return nil
}
