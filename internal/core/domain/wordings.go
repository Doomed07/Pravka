package core_domain

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"
)

// DocParagraph — абзац нашей редакции из единой версии разбора.
type DocParagraph struct {
	Index  int // номер абзаца в файле контрагента; у абзаца, удалённого контрагентом, — отрицательный
	Clause string
	Text   string
}

// MinWordingRunes — абзацы короче (заголовки разделов, «Приложение № 1») формулировками не считаются.
const MinWordingRunes = 40

// OurParagraphs — абзацы нашей редакции из единой версии (JSON поля document): совпадающий текст и то, что
// контрагент удалил (с отметкой и без). Вставки контрагента не входят. Шапка договора (абзацы без номера пункта:
// название, стороны, реквизиты) и короткие абзацы пропускаются.
func OurParagraphs(document []byte) ([]DocParagraph, error) {
	var doc []struct {
		Index    int    `json:"index"`
		Clause   string `json:"clause"`
		Segments []struct {
			K string `json:"k"`
			T string `json:"t"`
		} `json:"segments"`
	}
	if err := json.Unmarshal(document, &doc); err != nil {
		return nil, fmt.Errorf("единая версия: %w", err)
	}
	out := []DocParagraph{}
	for n, p := range doc {
		if strings.TrimSpace(p.Clause) == "" {
			continue
		}
		var b strings.Builder
		for _, s := range p.Segments {
			switch s.K {
			case "equal", "del", "silent_del":
				b.WriteString(s.T)
			}
		}
		text := strings.Join(strings.Fields(b.String()), " ")
		if utf8.RuneCountInString(text) < MinWordingRunes {
			continue
		}
		idx := p.Index
		if idx < 0 {
			idx = -(n + 1) // абзаца нет в файле контрагента: свой номер, не совпадающий с настоящими
		}
		out = append(out, DocParagraph{Index: idx, Clause: p.Clause, Text: text})
	}
	return out, nil
}

// Wording — «ваша прошлая формулировка»: абзац нашей редакции из другого разбора того же типа договора и роли,
// близкий по смыслу к нашему абзацу с правкой. Для встречной редакции: текст пишет юрист, программа только находит.
type Wording struct {
	ChangeID   string
	ReviewID   int
	TheirsName string
	CreatedAt  time.Time
	Clause     string
	Text       string
	Distance   float64
}

// MaxWordings — сколько разных прошлых формулировок показывать к правке.
const MaxWordings = 2

// WordingMaxDistance — дальше этого абзац прошлой редакции не показывается. Подобрано на 12 пунктах поставки и услуг:
// тот же пункт другими словами находится в 10 из 14 случаев, другой пункт (при той же обязанной стороне) — в 0 из 17.
const WordingMaxDistance = 0.18
