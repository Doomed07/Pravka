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

const columns = `id, user_id, created_at, theirs_name, base_name, playbook, playbook_name, our_role, contract_type, side, counts, warnings`

func scanReview(row core_postgres_pool.Row) (core_domain.ContractReview, error) {
	var (
		r                core_domain.ContractReview
		created          time.Time
		counts, warnings []byte
	)
	if err := row.Scan(&r.ID, &r.UserID, &created, &r.TheirsName, &r.BaseName, &r.Playbook, &r.PlaybookName,
		&r.OurRole, &r.ContractType, &r.Side, &counts, &warnings); err != nil {
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

// ListChoices — решения юриста по правкам разбора. Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ListChoices(ctx context.Context, userID, reviewID int) ([]core_domain.ReviewChoice, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	rows, err := r.pool.Query(ctx, `SELECT change_id, choice, text FROM pravkiapp.review_choices
	WHERE review_id = $1 ORDER BY change_id;`, reviewID)
	if err != nil {
		return nil, fmt.Errorf("select choices: %w", err)
	}
	defer rows.Close()
	out := []core_domain.ReviewChoice{}
	for rows.Next() {
		var c core_domain.ReviewChoice
		if err := rows.Scan(&c.ChangeID, &c.Choice, &c.Text); err != nil {
			return nil, fmt.Errorf("scan choice: %w", err)
		}
		out = append(out, c)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate choices: %w", err)
	}
	return out, nil
}

// SaveChoice — записать решение по правке; пустое решение удаляет запись. Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) SaveChoice(ctx context.Context, userID, reviewID int, c core_domain.ReviewChoice) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return err
	}
	if c.Choice == "" {
		if _, err := r.pool.Exec(ctx, `DELETE FROM pravkiapp.review_choices WHERE review_id = $1 AND change_id = $2;`,
			reviewID, c.ChangeID); err != nil {
			return fmt.Errorf("delete choice: %w", err)
		}
		return nil
	}
	_, err := r.pool.Exec(ctx, `
	INSERT INTO pravkiapp.review_choices (review_id, change_id, choice, text) VALUES ($1, $2, $3, $4)
	ON CONFLICT (review_id, change_id) DO UPDATE SET choice = EXCLUDED.choice, text = EXCLUDED.text, updated_at = NOW();`,
		reviewID, c.ChangeID, c.Choice, c.Text)
	if err != nil {
		return fmt.Errorf("save choice: %w", err)
	}
	return nil
}

// Похожесть прошлой правки на текущую: слова абзаца нашей редакции (вес 0,5) и суть правки — какие слова убраны
// и какие добавлены (вес 0,5). Правки с разными темами не сравниваются: «30% → 10%» в авансе и «30 → 10 дней» в сроке
// поставки дают одну и ту же суть {+10, -30}. «Та же правка» — та же суть в похожем абзаце (не меньше половины общих
// слов); её показываем первой. Остальные — если похожесть не ниже 0,35 при той же теме или не ниже 0,5, когда тема
// у одной из правок не определена. Пороги подобраны на учебных договорах (поставка и услуги); проверка —
// TestReviewsRepository_Precedents.
const precedentsQuery = `
WITH cur AS (
    SELECT contract_type, our_role FROM pravkiapp.reviews
    WHERE id = $1 AND user_id = $2 AND contract_type IN ('supply', 'services')
), mine AS (
    SELECT c->>'id' AS id, coalesce(c->>'topic', '') AS topic,
           lower(btrim(coalesce(c->>'before', ''))) AS b, lower(btrim(coalesce(c->>'after', ''))) AS a,
           pravkiapp.lexemes(c->>'context') AS ctx, pravkiapp.edit_sig(c->>'before', c->>'after') AS sig
    FROM pravkiapp.reviews r CROSS JOIN LATERAL jsonb_array_elements(r.changes) c
    WHERE r.id = $1 AND r.user_id = $2 AND coalesce(c->>'kind', '') <> 'comment'
), past AS (
    SELECT p.id AS review_id, rc.change_id AS past_change, p.theirs_name, p.created_at, rc.choice, rc.text,
           coalesce(c->>'clause', '') AS clause, coalesce(c->>'topic', '') AS topic,
           coalesce(c->>'before', '') AS before, coalesce(c->>'after', '') AS after,
           pravkiapp.lexemes(c->>'context') AS ctx, pravkiapp.edit_sig(c->>'before', c->>'after') AS sig
    FROM cur
    JOIN pravkiapp.reviews p ON p.user_id = $2 AND p.id <> $1 AND p.contract_type = cur.contract_type
                             AND p.our_role = cur.our_role
    JOIN pravkiapp.review_choices rc ON rc.review_id = p.id AND rc.choice IN ('accept', 'reject', 'counter')
    CROSS JOIN LATERAL jsonb_array_elements(p.changes) c
    WHERE c->>'id' = rc.change_id
), pairs AS (
    SELECT mine.id AS change_id, past.*, mine.topic = past.topic AND past.topic NOT IN ('', 'прочее') AS same_topic,
           pravkiapp.overlap(mine.ctx, past.ctx) AS ctx_score,
           (cardinality(mine.sig) > 0 AND mine.sig = past.sig)
             OR (lower(btrim(past.before)) = mine.b AND lower(btrim(past.after)) = mine.a) AS same_edit,
           0.5 * pravkiapp.overlap(mine.ctx, past.ctx) + 0.5 * pravkiapp.overlap(mine.sig, past.sig) AS score
    FROM mine CROSS JOIN past
    WHERE mine.topic = past.topic OR mine.topic IN ('', 'прочее') OR past.topic IN ('', 'прочее')
), scored AS (
    SELECT *, same_edit AND ctx_score >= 0.5 AS same FROM pairs
), ranked AS (
    SELECT *, row_number() OVER (PARTITION BY change_id ORDER BY same DESC, score DESC, created_at DESC) AS n
    FROM scored
    WHERE same OR (same_topic AND score >= 0.35) OR score >= 0.5
)
SELECT change_id, review_id, past_change, theirs_name, created_at, clause, topic, before, after, choice, text, same, score
FROM ranked WHERE n <= $3 ORDER BY change_id, n;`

// ListPrecedents — «как решали раньше» для правок разбора. Чужой разбор — ErrNotFound. Для договоров других типов
// (не поставка и не услуги) подсказок нет: пустой список.
func (r *ReviewsRepository) ListPrecedents(ctx context.Context, userID, reviewID int) ([]core_domain.Precedent, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	rows, err := r.pool.Query(ctx, precedentsQuery, reviewID, userID, core_domain.MaxPrecedents)
	if err != nil {
		return nil, fmt.Errorf("select precedents: %w", err)
	}
	defer rows.Close()
	out := []core_domain.Precedent{}
	for rows.Next() {
		var p core_domain.Precedent
		if err := rows.Scan(&p.ChangeID, &p.ReviewID, &p.PastChangeID, &p.TheirsName, &p.CreatedAt, &p.Clause, &p.Topic, &p.Before, &p.After,
			&p.Choice, &p.Text, &p.Same, &p.Score); err != nil {
			return nil, fmt.Errorf("scan precedent: %w", err)
		}
		out = append(out, p)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate precedents: %w", err)
	}
	return out, nil
}
