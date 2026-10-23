package core_domain

// LawPoint — пункт статьи закона (ГК РФ) для подсказок к правкам. Seq — порядок пункта в статье.
type LawPoint struct {
	Code      string `json:"code"`
	Article   string `json:"article"`
	Seq       int    `json:"seq"`
	Point     string `json:"point"`
	Title     string `json:"title"`
	Section   string `json:"section"`
	Chapter   string `json:"chapter"`
	Paragraph string `json:"paragraph"`
	Edited    string `json:"edited"`
	Text      string `json:"text"`
}
