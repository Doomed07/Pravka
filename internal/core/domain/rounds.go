package core_domain

import (
	"encoding/json"
	"fmt"
)

// Как правка текущего раунда связана с прошлыми раундами того же договора.
const (
	RelationNew      = "new"      // раньше не встречалась
	RelationRepeat   = "repeat"   // та же правка слово в слово
	RelationReturned = "returned" // тот же пункт и тема, но другое значение: контрагент вернулся к пункту
)

// RoundChange — правка раунда в том виде, в каком она нужна для сравнения раундов.
type RoundChange struct {
	ID          string
	Fingerprint string // отпечаток движка: «было», «стало» и вид правки
	Clause      string
	Topic       string
	Kind        string
	Before      string
	After       string
}

// RoundSource — прошлый раунд: его правки и решения юриста по ним.
type RoundSource struct {
	ReviewID  int
	Round     int
	Changes   []RoundChange
	Decisions map[string]ReviewChoice // номер правки → решение
}

// RoundLink — связь правки текущего раунда с правкой из прошлого раунда (ближайшего, где она встретилась).
type RoundLink struct {
	ChangeID     string
	Relation     string
	Round        int
	ReviewID     int
	PastChangeID string
	PastBefore   string
	PastAfter    string
	Decision     string // решение юриста по прошлой правке: accept, reject, counter; пусто — не решал
	DecisionText string
}

// RoundClosed — правка прошлого раунда, которой нет в текущем: контрагент её снял или принял нашу встречную.
type RoundClosed struct {
	Round        int
	ReviewID     int
	ChangeID     string
	Clause       string
	Topic        string
	Before       string
	After        string
	Decision     string
	DecisionText string
}

// RoundComparison — итог сравнения текущего раунда с прошлыми.
type RoundComparison struct {
	Links  []RoundLink // по одной на каждую значимую правку текущего раунда
	Closed []RoundClosed
}

// Count — сколько правок текущего раунда с таким отношением к прошлым.
func (c RoundComparison) Count(relation string) int {
	n := 0
	for _, l := range c.Links {
		if l.Relation == relation {
			n++
		}
	}
	return n
}

// ParseRoundChanges читает список правок разбора (JSON поля changes). Комментарии и технические правки (опечатки,
// знаки) в сравнение не входят: они не предмет торга.
func ParseRoundChanges(changes []byte) ([]RoundChange, error) {
	var list []struct {
		ID          string `json:"id"`
		Fingerprint string `json:"fingerprint"`
		Clause      string `json:"clause"`
		Topic       string `json:"topic"`
		Kind        string `json:"kind"`
		Source      string `json:"source"`
		Before      string `json:"before"`
		After       string `json:"after"`
		Materiality string `json:"materiality"`
	}
	if err := json.Unmarshal(changes, &list); err != nil {
		return nil, fmt.Errorf("правки разбора: %w", err)
	}
	out := []RoundChange{}
	for _, c := range list {
		// замечания к положениям первой версии (source «clause») правками контрагента не были: в раундах не сравниваются
		if c.Kind == "comment" || c.Materiality == "техническая" || c.Source == "clause" {
			continue
		}
		out = append(out, RoundChange{ID: c.ID, Fingerprint: c.Fingerprint, Clause: c.Clause, Topic: c.Topic,
			Kind: c.Kind, Before: shortText(c.Before), After: shortText(c.After)})
	}
	return out, nil
}

// CompareRounds сравнивает правки текущего раунда с прошлыми (earlier — от старого к новому). Идёт от ближайшего
// раунда к дальнему; в раунде сначала ищется та же правка, затем тот же пункт и тема с другим значением (тема не
// пустая и не «прочее»: иначе под «тот же пункт» попадёт всё подряд). Прошлое решение юриста показывается как есть.
// Closed — правки последнего прошлого раунда, к которым не привязана ни одна правка текущего: более давние уже были
// закрыты раньше.
func CompareRounds(cur []RoundChange, earlier []RoundSource) RoundComparison {
	out := RoundComparison{Links: make([]RoundLink, 0, len(cur))}
	matched := map[string]bool{} // «раунд:правка» прошлых раундов, к которым что-то привязано
	for _, c := range cur {
		link := RoundLink{ChangeID: c.ID, Relation: RelationNew}
		for i := len(earlier) - 1; i >= 0 && link.Relation == RelationNew; i-- {
			src := earlier[i]
			if past, ok := findRepeat(c, src.Changes); ok {
				link = roundLink(c.ID, RelationRepeat, src, past)
			} else if past, ok := findReturned(c, src.Changes); ok {
				link = roundLink(c.ID, RelationReturned, src, past)
			}
		}
		if link.Relation != RelationNew {
			matched[fmt.Sprintf("%d:%s", link.ReviewID, link.PastChangeID)] = true
		}
		out.Links = append(out.Links, link)
	}
	if n := len(earlier); n > 0 {
		last := earlier[n-1]
		for _, p := range last.Changes {
			if matched[fmt.Sprintf("%d:%s", last.ReviewID, p.ID)] {
				continue
			}
			d := last.Decisions[p.ID]
			out.Closed = append(out.Closed, RoundClosed{Round: last.Round, ReviewID: last.ReviewID, ChangeID: p.ID,
				Clause: p.Clause, Topic: p.Topic, Before: p.Before, After: p.After, Decision: d.Choice, DecisionText: d.Text})
		}
	}
	return out
}

func findRepeat(c RoundChange, past []RoundChange) (RoundChange, bool) {
	if c.Fingerprint == "" {
		return RoundChange{}, false
	}
	for _, p := range past {
		if p.Fingerprint == c.Fingerprint {
			return p, true
		}
	}
	return RoundChange{}, false
}

func findReturned(c RoundChange, past []RoundChange) (RoundChange, bool) {
	if c.Clause == "" || c.Topic == "" || c.Topic == OtherTopic {
		return RoundChange{}, false
	}
	for _, p := range past {
		if p.Clause == c.Clause && p.Topic == c.Topic && p.Fingerprint != c.Fingerprint {
			return p, true
		}
	}
	return RoundChange{}, false
}

func roundLink(changeID, relation string, src RoundSource, past RoundChange) RoundLink {
	d := src.Decisions[past.ID]
	return RoundLink{ChangeID: changeID, Relation: relation, Round: src.Round, ReviewID: src.ReviewID, PastChangeID: past.ID,
		PastBefore: past.Before, PastAfter: past.After, Decision: d.Choice, DecisionText: d.Text}
}
