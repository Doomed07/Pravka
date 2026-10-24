package reviews_repository_postgres

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

// ---------- разбор ----------

const columns = `id, user_id, created_at, theirs_name, base_name, playbook, playbook_name, our_role, contract_type, side, counts, warnings`

// ReviewModel — строка pravkiapp.reviews (без тяжёлых частей): counts и warnings — JSON.
type ReviewModel struct {
	ID           int
	UserID       int
	CreatedAt    time.Time
	TheirsName   string
	BaseName     string
	Playbook     string
	PlaybookName string
	OurRole      string
	ContractType string
	Side         string
	Counts       []byte
	Warnings     []byte
}

func scanReview(row core_postgres_pool.Row) (core_domain.ContractReview, error) {
	var m ReviewModel
	if err := row.Scan(&m.ID, &m.UserID, &m.CreatedAt, &m.TheirsName, &m.BaseName, &m.Playbook, &m.PlaybookName,
		&m.OurRole, &m.ContractType, &m.Side, &m.Counts, &m.Warnings); err != nil {
		return core_domain.ContractReview{}, err
	}
	return reviewDomainFromModel(m)
}

func reviewDomainFromModel(m ReviewModel) (core_domain.ContractReview, error) {
	r := core_domain.ContractReview{
		ID: m.ID, UserID: m.UserID, CreatedAt: m.CreatedAt, TheirsName: m.TheirsName, BaseName: m.BaseName,
		Playbook: m.Playbook, PlaybookName: m.PlaybookName, OurRole: m.OurRole, ContractType: m.ContractType, Side: m.Side,
	}
	if err := json.Unmarshal(m.Counts, &r.Counts); err != nil {
		return core_domain.ContractReview{}, fmt.Errorf("decode counts: %w", err)
	}
	if err := json.Unmarshal(m.Warnings, &r.Warnings); err != nil {
		return core_domain.ContractReview{}, fmt.Errorf("decode warnings: %w", err)
	}
	return r, nil
}

// ---------- решение юриста ----------

type ChoiceModel struct {
	ChangeID string
	Choice   string
	Text     string
}

func choiceDomainFromModel(m ChoiceModel) core_domain.ReviewChoice {
	return core_domain.ReviewChoice{ChangeID: m.ChangeID, Choice: m.Choice, Text: m.Text}
}

// ---------- как решали раньше ----------

// PrecedentModel — прошлое решение по похожей правке. По словам: Same и Score из запроса; по смыслу — Distance.
type PrecedentModel struct {
	ChangeID     string
	ReviewID     int
	PastChangeID string
	TheirsName   string
	CreatedAt    time.Time
	Clause       string
	Topic        string
	Before       string
	After        string
	Choice       string
	Text         string
	Same         bool
	Score        float64
	Distance     float64
}

func precedentDomainFromModel(m PrecedentModel, semantic bool) core_domain.Precedent {
	p := core_domain.Precedent{
		ChangeID: m.ChangeID, ReviewID: m.ReviewID, PastChangeID: m.PastChangeID, TheirsName: m.TheirsName,
		CreatedAt: m.CreatedAt, Clause: m.Clause, Topic: m.Topic, Before: m.Before, After: m.After, Choice: m.Choice,
		Text: m.Text, Same: m.Same, Score: m.Score,
	}
	if semantic {
		p.Semantic, p.Score = true, 1-m.Distance
	}
	return p
}

// ---------- векторы: правки, абзацы нашей редакции ----------

type VectorChangeModel struct {
	ID           string
	Kind         string
	Topic        string
	Context      string
	ContextAfter string
}

func vectorChangeDomainFromModel(m VectorChangeModel) core_domain.VectorChange {
	return core_domain.VectorChange{ID: m.ID, Kind: m.Kind, Topic: m.Topic, Context: m.Context, ContextAfter: m.ContextAfter}
}

// vectorLiteral — вектор в записи pgvector: [0.1,0.2,…].
func vectorLiteral(v []float32) string {
	parts := make([]string, len(v))
	for i, x := range v {
		parts[i] = strconv.FormatFloat(float64(x), 'g', -1, 32)
	}
	return "[" + strings.Join(parts, ",") + "]"
}

// ---------- что говорит ГК ----------

type LawHintModel struct {
	ChangeID string
	Article  string
	Point    string
	Title    string
	Chapter  string
	Edited   string
	Text     string
	Distance float64
}

func lawHintDomainFromModel(m LawHintModel) core_domain.LawHint {
	return core_domain.LawHint{ChangeID: m.ChangeID, Article: m.Article, Point: m.Point, Title: m.Title, Chapter: m.Chapter,
		Edited: m.Edited, Text: m.Text, Distance: m.Distance}
}

// ---------- ваши прошлые формулировки ----------

type WordingModel struct {
	ChangeID   string
	ReviewID   int
	TheirsName string
	CreatedAt  time.Time
	Clause     string
	Text       string
	Distance   float64
}

func wordingDomainFromModel(m WordingModel) core_domain.Wording {
	return core_domain.Wording{ChangeID: m.ChangeID, ReviewID: m.ReviewID, TheirsName: m.TheirsName, CreatedAt: m.CreatedAt,
		Clause: m.Clause, Text: m.Text, Distance: m.Distance}
}
