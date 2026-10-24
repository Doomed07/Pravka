package reviews_repository_postgres

import (
	"context"
	"errors"
	"fmt"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

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
