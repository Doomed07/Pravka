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

// LawHint — «что говорит ГК»: пункт статьи, ближайший по смыслу к правке. Только подсказка: норму к спору
// оценивает юрист.
type LawHint struct {
	ChangeID string
	Article  string
	Point    string
	Title    string
	Chapter  string
	Edited   string
	Text     string
	Distance float64 // косинусное расстояние: меньше — ближе
}

// MaxLawHints — сколько пунктов ГК показывать к одной правке.
const MaxLawHints = 3

// LawHintMaxDistance — дальше этого пункт не показывается (подобрано на учебных договорах поставки и услуг:
// у верных подсказок расстояние не больше 0,41).
const LawHintMaxDistance = 0.42

// NoLawTopics — темы, к которым ГК не подсказывается: их регулируют другие законы (налоги — НК РФ, подсудность —
// АПК РФ, персональные данные — 152-ФЗ, первичные документы — 402-ФЗ), реквизиты сверяются отдельно,
// интеллектуальная собственность — часть четвёртая ГК, её в подборке пока нет. Пустая тема — опечатки и грамматика.
var NoLawTopics = []string{"", "прочее", "налоги", "разрешение споров", "персональные данные и ИБ", "стороны и реквизиты",
	"первичные документы и ЭДО", "интеллектуальная собственность"}

// VectorChange — правка разбора, для которой ещё нет вектора: из чего он считается.
type VectorChange struct {
	ID           string
	Kind         string
	Topic        string
	Context      string
	ContextAfter string
}

// EmbedText — что сравнивается с ГК: тема правки и абзац (после правки; для удаления — прежний абзац, где было
// удалённое условие). На учебных договорах так нужная статья попадает в первые три чаще, чем по одному абзацу или
// по «было / стало».
func (c VectorChange) EmbedText() string {
	para := c.ContextAfter
	if c.Kind == "delete" || c.Kind == "para_delete" || para == "" {
		para = c.Context
	}
	text := para
	if c.Topic != "" && c.Topic != "прочее" {
		text = c.Topic + ". " + para
	}
	r := []rune(text)
	if len(r) > 2000 {
		r = r[:2000]
	}
	return string(r)
}
