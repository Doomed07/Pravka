package reviews_repository_postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
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
// поставки дают одну и ту же суть {+10, -30}. Не сравниваются и правки с разной обязанной стороной (неустойка
// Заказчика ≠ неустойка Исполнителя, pravkiapp.same_obligor). «Та же правка» — та же суть в похожем абзаце (не меньше
// половины общих слов); её показываем первой. Остальные — если похожесть не ниже 0,35 при той же теме или не ниже 0,5, когда тема
// у одной из правок не определена. Пороги подобраны на учебных договорах (поставка и услуги); проверка —
// TestReviewsRepository_Precedents.
const precedentsQuery = `
WITH cur AS (
    SELECT contract_type, our_role FROM pravkiapp.reviews
    WHERE id = $1 AND user_id = $2 AND contract_type IN ('supply', 'services')
), mine AS (
    SELECT c->>'id' AS id, coalesce(c->>'topic', '') AS topic,
           lower(btrim(coalesce(c->>'before', ''))) AS b, lower(btrim(coalesce(c->>'after', ''))) AS a,
           pravkiapp.lexemes(c->>'context') AS ctx, pravkiapp.edit_sig(c->>'before', c->>'after') AS sig,
           coalesce(nullif(c->>'context_after', ''), c->>'context') AS para
    FROM pravkiapp.reviews r CROSS JOIN LATERAL jsonb_array_elements(r.changes) c
    WHERE r.id = $1 AND r.user_id = $2 AND coalesce(c->>'kind', '') <> 'comment'
), past AS (
    SELECT p.id AS review_id, rc.change_id AS past_change, p.theirs_name, p.created_at, rc.choice, rc.text,
           coalesce(c->>'clause', '') AS clause, coalesce(c->>'topic', '') AS topic,
           coalesce(c->>'before', '') AS before, coalesce(c->>'after', '') AS after,
           pravkiapp.lexemes(c->>'context') AS ctx, pravkiapp.edit_sig(c->>'before', c->>'after') AS sig,
           coalesce(nullif(c->>'context_after', ''), c->>'context') AS para
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
    WHERE (mine.topic = past.topic OR mine.topic IN ('', 'прочее') OR past.topic IN ('', 'прочее'))
      AND pravkiapp.same_obligor(mine.para, past.para)
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

// ChangesWithoutVectors — правки разбора без посчитанного вектора (для «Что говорит ГК» и «как решали раньше» по
// смыслу). Только поставка и услуги; комментарии и технические правки (опечатки, пунктуация) пропускаются.
// Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ChangesWithoutVectors(ctx context.Context, userID, reviewID int) ([]core_domain.VectorChange, error) {
	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	return r.changesWithoutVectors(ctx, reviewID)
}

func (r *ReviewsRepository) changesWithoutVectors(ctx context.Context, reviewID int) ([]core_domain.VectorChange, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	rows, err := r.pool.Query(ctx, `
	SELECT c->>'id', coalesce(c->>'kind', ''), coalesce(c->>'topic', ''), coalesce(c->>'context', ''),
	       coalesce(c->>'context_after', '')
	FROM pravkiapp.reviews r CROSS JOIN LATERAL jsonb_array_elements(r.changes) c
	WHERE r.id = $1 AND r.contract_type IN ('supply', 'services') AND coalesce(c->>'kind', '') <> 'comment'
	  AND coalesce(c->>'materiality', '') <> 'техническая'
	  AND NOT EXISTS (SELECT 1 FROM pravkiapp.review_vectors v WHERE v.review_id = r.id AND v.change_id = c->>'id');`,
		reviewID)
	if err != nil {
		return nil, fmt.Errorf("select changes without vectors: %w", err)
	}
	defer rows.Close()
	out := []core_domain.VectorChange{}
	for rows.Next() {
		var c core_domain.VectorChange
		if err := rows.Scan(&c.ID, &c.Kind, &c.Topic, &c.Context, &c.ContextAfter); err != nil {
			return nil, fmt.Errorf("scan change: %w", err)
		}
		out = append(out, c)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate changes: %w", err)
	}
	return out, nil
}

func vectorLiteral(v []float32) string {
	parts := make([]string, len(v))
	for i, x := range v {
		parts[i] = strconv.FormatFloat(float64(x), 'g', -1, 32)
	}
	return "[" + strings.Join(parts, ",") + "]"
}

// SaveVectors — векторы правок разбора (по номеру правки), посчитанные моделью model.
func (r *ReviewsRepository) SaveVectors(ctx context.Context, reviewID int, model string, vectors map[string][]float32) error {
	if len(vectors) == 0 {
		return nil
	}
	ids, lits := make([]string, 0, len(vectors)), make([]string, 0, len(vectors))
	for id, v := range vectors {
		ids, lits = append(ids, id), append(lits, vectorLiteral(v))
	}
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	_, err := r.pool.Exec(ctx, `
	INSERT INTO pravkiapp.review_vectors (review_id, change_id, model, embedding)
	SELECT $1, id, $2, lit::vector FROM unnest($3::text[], $4::text[]) AS x(id, lit)
	ON CONFLICT (review_id, change_id) DO UPDATE SET model = EXCLUDED.model, embedding = EXCLUDED.embedding;`,
		reviewID, model, ids, lits)
	if err != nil {
		return fmt.Errorf("save vectors: %w", err)
	}
	return nil
}

// ListLawHints — «что говорит ГК» к правкам разбора: до $3 ближайших по смыслу пунктов ГК в частях кодекса для этого
// типа договора (pravkiapp.in_law_scope), не дальше $3; темы из core_domain.NoLawTopics пропускаются.
// Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ListLawHints(ctx context.Context, userID, reviewID int) ([]core_domain.LawHint, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	rows, err := r.pool.Query(ctx, `
	SELECT v.change_id, h.article, h.point, h.title, h.chapter, h.edited, h.text, h.distance
	FROM pravkiapp.reviews r
	JOIN pravkiapp.review_vectors v ON v.review_id = r.id
	JOIN LATERAL jsonb_array_elements(r.changes) c ON c->>'id' = v.change_id
	CROSS JOIN LATERAL (
	    SELECT p.article, p.point, p.title, p.chapter, p.edited, p.text, p.embedding <=> v.embedding AS distance
	    FROM pravkiapp.law_points p
	    WHERE p.code = 'ГК РФ' AND p.embedding IS NOT NULL AND pravkiapp.in_law_scope(r.contract_type, p.article)
	    ORDER BY p.embedding <=> v.embedding
	    LIMIT $2
	) h
	WHERE r.id = $1 AND r.contract_type IN ('supply', 'services') AND h.distance <= $3
	  AND NOT (coalesce(c->>'topic', '') = ANY($4))
	ORDER BY v.change_id, h.distance;`, reviewID, core_domain.MaxLawHints, core_domain.LawHintMaxDistance, core_domain.NoLawTopics)
	if err != nil {
		return nil, fmt.Errorf("select law hints: %w", err)
	}
	defer rows.Close()
	out := []core_domain.LawHint{}
	for rows.Next() {
		var h core_domain.LawHint
		if err := rows.Scan(&h.ChangeID, &h.Article, &h.Point, &h.Title, &h.Chapter, &h.Edited, &h.Text, &h.Distance); err != nil {
			return nil, fmt.Errorf("scan law hint: %w", err)
		}
		out = append(out, h)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate law hints: %w", err)
	}
	return out, nil
}

// ---------- индексация разборов: векторы абзацев нашей редакции и правок ----------

// ReviewsToIndex — разборы поставки и услуг, у которых ещё нет векторов (старые сначала). Для фоновой индексации.
func (r *ReviewsRepository) ReviewsToIndex(ctx context.Context, limit int) ([]int, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	rows, err := r.pool.Query(ctx, `SELECT id FROM pravkiapp.reviews
	WHERE indexed_at IS NULL AND contract_type IN ('supply', 'services') ORDER BY created_at, id LIMIT $1;`, limit)
	if err != nil {
		return nil, fmt.Errorf("select reviews to index: %w", err)
	}
	defer rows.Close()
	out := []int{}
	for rows.Next() {
		var id int
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("scan review id: %w", err)
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

// NeedsIndex — разбор пользователя ещё не проиндексирован (и это поставка или услуги). Чужой — ErrNotFound.
func (r *ReviewsRepository) NeedsIndex(ctx context.Context, userID, reviewID int) (bool, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	var need bool
	err := r.pool.QueryRow(ctx, `SELECT indexed_at IS NULL AND contract_type IN ('supply', 'services')
	FROM pravkiapp.reviews WHERE id = $1 AND user_id = $2;`, reviewID, userID).Scan(&need)
	if errors.Is(err, core_postgres_pool.ErrNoRows) {
		return false, fmt.Errorf("review %d: %w", reviewID, core_errors.ErrNotFound)
	}
	if err != nil {
		return false, fmt.Errorf("select index state: %w", err)
	}
	return need, nil
}

// IndexSource — что индексировать в разборе: единая версия (JSON) и правки без векторов. Без проверки владельца:
// только для фоновой индексации и после NeedsIndex.
func (r *ReviewsRepository) IndexSource(ctx context.Context, reviewID int) ([]byte, []core_domain.VectorChange, error) {
	c, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	var document []byte
	err := r.pool.QueryRow(c, `SELECT convert_to(document::text, 'UTF8') FROM pravkiapp.reviews WHERE id = $1;`, reviewID).Scan(&document)
	if err != nil {
		return nil, nil, fmt.Errorf("select document: %w", err)
	}
	changes, err := r.changesWithoutVectors(ctx, reviewID)
	return document, changes, err
}

// SaveParagraphs — абзацы нашей редакции разбора с векторами (по одному на абзац).
func (r *ReviewsRepository) SaveParagraphs(ctx context.Context, reviewID int, model string, paras []core_domain.DocParagraph, vectors [][]float32) error {
	if len(paras) == 0 {
		return nil
	}
	if len(vectors) != len(paras) {
		return fmt.Errorf("векторов %d, абзацев %d", len(vectors), len(paras))
	}
	idx, clauses, texts, lits := make([]int32, len(paras)), make([]string, len(paras)), make([]string, len(paras)), make([]string, len(paras))
	for i, p := range paras {
		idx[i], clauses[i], texts[i], lits[i] = int32(p.Index), p.Clause, p.Text, vectorLiteral(vectors[i])
	}
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	_, err := r.pool.Exec(ctx, `
	INSERT INTO pravkiapp.review_paragraphs (review_id, idx, clause, text, model, embedding)
	SELECT $1, i, left(c, 50), t, $2, l::vector FROM unnest($3::int[], $4::text[], $5::text[], $6::text[]) AS x(i, c, t, l)
	ON CONFLICT (review_id, idx) DO UPDATE SET clause = EXCLUDED.clause, text = EXCLUDED.text, model = EXCLUDED.model,
	                                           embedding = EXCLUDED.embedding;`,
		reviewID, model, idx, clauses, texts, lits)
	if err != nil {
		return fmt.Errorf("save paragraphs: %w", err)
	}
	return nil
}

// MarkIndexed — векторы абзацев и правок разбора посчитаны.
func (r *ReviewsRepository) MarkIndexed(ctx context.Context, reviewID int) error {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.pool.Exec(ctx, `UPDATE pravkiapp.reviews SET indexed_at = NOW() WHERE id = $1;`, reviewID); err != nil {
		return fmt.Errorf("mark indexed: %w", err)
	}
	return nil
}

// ---------- ваши прошлые формулировки ----------

// ListWordings — к правке разбора: абзацы нашей редакции из других разборов того же юриста, типа договора и роли,
// ближайшие по смыслу к нашему абзацу с этой правкой (не дальше core_domain.WordingMaxDistance). Тот же текст
// (тот же шаблон) и пункт с другой обязанной стороной (неустойка Покупателя к неустойке Поставщика) не показываются;
// одинаковые тексты из разных разборов — один раз. Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ListWordings(ctx context.Context, userID, reviewID int) ([]core_domain.Wording, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	rows, err := r.pool.Query(ctx, `
	WITH cur AS (
	    SELECT id, contract_type, our_role, changes FROM pravkiapp.reviews
	    WHERE id = $1 AND user_id = $2 AND contract_type IN ('supply', 'services')
	), mine AS (
	    SELECT c->>'id' AS change_id, p.text, p.embedding
	    FROM cur CROSS JOIN LATERAL jsonb_array_elements(cur.changes) c
	    JOIN pravkiapp.review_paragraphs p ON p.review_id = cur.id AND p.idx = (c->>'paragraph_index')::int
	    WHERE coalesce(c->>'kind', '') <> 'comment' AND coalesce(c->>'materiality', '') <> 'техническая'
	      AND coalesce(c->>'topic', '') <> 'стороны и реквизиты'
	), found AS (
	    SELECT mine.change_id, w.*, row_number() OVER (PARTITION BY mine.change_id, w.norm ORDER BY w.distance) AS dup
	    FROM mine CROSS JOIN cur CROSS JOIN LATERAL (
	        SELECT p.review_id, r.theirs_name, r.created_at, p.clause, p.text, p.embedding <=> mine.embedding AS distance,
	               regexp_replace(lower(p.text), '\s+', ' ', 'g') AS norm
	        FROM pravkiapp.review_paragraphs p JOIN pravkiapp.reviews r ON r.id = p.review_id
	        WHERE r.user_id = $2 AND r.id <> cur.id AND r.contract_type = cur.contract_type AND r.our_role = cur.our_role
	          AND regexp_replace(lower(p.text), '\s+', ' ', 'g') <> regexp_replace(lower(mine.text), '\s+', ' ', 'g')
	          AND pravkiapp.same_obligor(p.text, mine.text)
	        ORDER BY distance LIMIT 20
	    ) w
	    WHERE w.distance <= $3
	), ranked AS (
	    SELECT *, row_number() OVER (PARTITION BY change_id ORDER BY distance, created_at DESC) AS n FROM found WHERE dup = 1
	)
	SELECT change_id, review_id, theirs_name, created_at, clause, text, distance FROM ranked WHERE n <= $4
	ORDER BY change_id, n;`, reviewID, userID, core_domain.WordingMaxDistance, core_domain.MaxWordings)
	if err != nil {
		return nil, fmt.Errorf("select wordings: %w", err)
	}
	defer rows.Close()
	out := []core_domain.Wording{}
	for rows.Next() {
		var w core_domain.Wording
		if err := rows.Scan(&w.ChangeID, &w.ReviewID, &w.TheirsName, &w.CreatedAt, &w.Clause, &w.Text, &w.Distance); err != nil {
			return nil, fmt.Errorf("scan wording: %w", err)
		}
		out = append(out, w)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate wordings: %w", err)
	}
	return out, nil
}

// ---------- как решали раньше: по смыслу ----------

// ListSemanticPrecedents — «как решали раньше» по смыслу: к правкам разбора, кроме skip (у них уже есть подсказки
// по словам), — прошлые решения юриста по правкам, близким по вектору (не дальше core_domain.SemanticPrecedentMaxDistance),
// того же типа договора, роли, темы и обязанной стороны (как и в поиске по словам).
// Чужой разбор — ErrNotFound.
func (r *ReviewsRepository) ListSemanticPrecedents(ctx context.Context, userID, reviewID int, skip []string) ([]core_domain.Precedent, error) {
	ctx, cancel := context.WithTimeout(ctx, r.pool.OpTimeout())
	defer cancel()

	if _, err := r.GetReview(ctx, userID, reviewID); err != nil {
		return nil, err
	}
	if skip == nil {
		skip = []string{}
	}
	rows, err := r.pool.Query(ctx, `
	WITH cur AS (
	    SELECT id, contract_type, our_role, changes FROM pravkiapp.reviews
	    WHERE id = $1 AND user_id = $2 AND contract_type IN ('supply', 'services')
	), mine AS (
	    SELECT v.change_id, v.embedding, coalesce(c->>'topic', '') AS topic,
	           coalesce(nullif(c->>'context_after', ''), c->>'context') AS para
	    FROM cur JOIN pravkiapp.review_vectors v ON v.review_id = cur.id
	    JOIN LATERAL jsonb_array_elements(cur.changes) c ON c->>'id' = v.change_id
	    WHERE NOT (v.change_id = ANY($3))
	), found AS (
	    SELECT mine.change_id, s.*, row_number() OVER (PARTITION BY mine.change_id ORDER BY s.distance, s.created_at DESC) AS n
	    FROM mine CROSS JOIN cur CROSS JOIN LATERAL (
	        SELECT p.id AS review_id, rc.change_id AS past_change, p.theirs_name, p.created_at, rc.choice, rc.text,
	               coalesce(c->>'clause', '') AS clause, coalesce(c->>'topic', '') AS topic,
	               coalesce(c->>'before', '') AS before, coalesce(c->>'after', '') AS after,
	               pv.embedding <=> mine.embedding AS distance
	        FROM pravkiapp.reviews p
	        JOIN pravkiapp.review_choices rc ON rc.review_id = p.id AND rc.choice IN ('accept', 'reject', 'counter')
	        JOIN pravkiapp.review_vectors pv ON pv.review_id = p.id AND pv.change_id = rc.change_id
	        JOIN LATERAL jsonb_array_elements(p.changes) c ON c->>'id' = rc.change_id
	        WHERE p.user_id = $2 AND p.id <> cur.id AND p.contract_type = cur.contract_type AND p.our_role = cur.our_role
	          AND (coalesce(c->>'topic', '') = mine.topic OR mine.topic IN ('', 'прочее')
	               OR coalesce(c->>'topic', '') IN ('', 'прочее'))
	          AND pravkiapp.same_obligor(mine.para, coalesce(nullif(c->>'context_after', ''), c->>'context'))
	        ORDER BY distance LIMIT $5
	    ) s
	    WHERE s.distance <= $4
	)
	SELECT change_id, review_id, past_change, theirs_name, created_at, clause, topic, before, after, choice, text, distance
	FROM found WHERE n <= $5 ORDER BY change_id, n;`,
		reviewID, userID, skip, core_domain.SemanticPrecedentMaxDistance, core_domain.MaxPrecedents)
	if err != nil {
		return nil, fmt.Errorf("select semantic precedents: %w", err)
	}
	defer rows.Close()
	out := []core_domain.Precedent{}
	for rows.Next() {
		var p core_domain.Precedent
		var dist float64
		if err := rows.Scan(&p.ChangeID, &p.ReviewID, &p.PastChangeID, &p.TheirsName, &p.CreatedAt, &p.Clause, &p.Topic,
			&p.Before, &p.After, &p.Choice, &p.Text, &dist); err != nil {
			return nil, fmt.Errorf("scan semantic precedent: %w", err)
		}
		p.Semantic, p.Score = true, 1-dist
		out = append(out, p)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate semantic precedents: %w", err)
	}
	return out, nil
}
