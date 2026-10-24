package law_repository_postgres

import (
	"strconv"
	"strings"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// LawPointModel — строка pravkiapp.law_points для вставки (через jsonb_to_recordset): пункт и его вектор.
type LawPointModel struct {
	Code      string  `json:"code"`
	Article   string  `json:"article"`
	Seq       int     `json:"seq"`
	Point     string  `json:"point"`
	Title     string  `json:"title"`
	Section   string  `json:"section"`
	Chapter   string  `json:"chapter"`
	Paragraph string  `json:"paragraph"`
	Edited    string  `json:"edited"`
	Text      string  `json:"text"`
	Embedding *string `json:"embedding"` // nil — без вектора
}

func lawPointModelFromDomain(p core_domain.LawPoint, vector []float32) LawPointModel {
	return LawPointModel{Code: p.Code, Article: p.Article, Seq: p.Seq, Point: p.Point, Title: p.Title, Section: p.Section,
		Chapter: p.Chapter, Paragraph: p.Paragraph, Edited: p.Edited, Text: p.Text, Embedding: vectorLiteral(vector)}
}

// vectorLiteral — вектор в записи pgvector: [0.1,0.2,…]. nil — NULL (без вектора).
func vectorLiteral(v []float32) *string {
	if v == nil {
		return nil
	}
	parts := make([]string, len(v))
	for i, x := range v {
		parts[i] = strconv.FormatFloat(float64(x), 'g', -1, 32)
	}
	s := "[" + strings.Join(parts, ",") + "]"
	return &s
}
