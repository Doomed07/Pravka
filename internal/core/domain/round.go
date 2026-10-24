package core_domain

import (
	"encoding/json"
	"fmt"
	"strings"
	"unicode/utf8"
)

// Вывод плейбука по правке — как на странице разбора: «решает юрист» важнее уровня правила.
const (
	VerdictLawyer   = "lawyer"
	VerdictAgreed   = "agreed"
	VerdictReject   = "reject"
	VerdictFallback = "fallback"
	VerdictAccept   = "accept"
	VerdictNone     = "none"
)

// OtherTopic — правки без темы; в сводке идут последними.
const OtherTopic = "прочее"

// RoundTextRunes — сколько знаков текста правки показывать в сводке.
const RoundTextRunes = 90

// RoundItem — одна правка в сводке раунда: где, что было и что стало, вывод плейбука.
type RoundItem struct {
	ChangeID string
	Clause   string
	Kind     string // как в движке: replace, insert, delete, para_insert, para_delete, move, comment
	Verdict  string
	Silent   bool // без отметки в рецензировании
	Before   string
	After    string
}

// RoundTopic — правки одной темы и сколько из них с каждым выводом плейбука.
type RoundTopic struct {
	Topic    string
	Verdicts map[string]int
	Silent   int
	Deleted  int // удалено из нашей редакции (слова или пункт целиком)
	Items    []RoundItem
}

// RoundSummary — сводка раунда по темам. Технические правки (опечатки, знаки) в темы не входят, только их число.
type RoundSummary struct {
	Topics    []RoundTopic
	Technical int
}

// SummarizeRound собирает сводку из списка правок разбора (JSON поля changes). Темы идут в порядке первой правки:
// движок уже отсортировал правки по приоритету плейбука (стороны и реквизиты, затем убытки, ограничение
// ответственности, расторжение); правки без темы — в конце. Текст только из самих правок, без пересказа.
func SummarizeRound(changes []byte) (RoundSummary, error) {
	var list []struct {
		ID          string `json:"id"`
		Source      string `json:"source"`
		Kind        string `json:"kind"`
		Clause      string `json:"clause"`
		Before      string `json:"before"`
		After       string `json:"after"`
		Topic       string `json:"topic"`
		Materiality string `json:"materiality"`
		Level       string `json:"level"`
		Action      string `json:"action"`
		Lawyer      bool   `json:"lawyer_decision_needed"`
	}
	if err := json.Unmarshal(changes, &list); err != nil {
		return RoundSummary{}, fmt.Errorf("правки разбора: %w", err)
	}
	out := RoundSummary{Topics: []RoundTopic{}}
	var other *RoundTopic
	pos := map[string]int{}
	for _, c := range list {
		if c.Materiality == "техническая" && c.Kind != "comment" {
			out.Technical++
			continue
		}
		var t *RoundTopic
		if c.Topic == "" || c.Topic == OtherTopic {
			if other == nil {
				other = &RoundTopic{Topic: OtherTopic, Verdicts: map[string]int{}}
			}
			t = other
		} else {
			i, ok := pos[c.Topic]
			if !ok {
				i = len(out.Topics)
				pos[c.Topic] = i
				out.Topics = append(out.Topics, RoundTopic{Topic: c.Topic, Verdicts: map[string]int{}})
			}
			t = &out.Topics[i]
		}
		item := RoundItem{ChangeID: c.ID, Clause: c.Clause, Kind: c.Kind,
			Verdict: verdictOf(c.Lawyer, c.Action, c.Level), Silent: c.Source == "silent" || c.Source == "diff",
			Before: shortText(c.Before), After: shortText(c.After)}
		t.Verdicts[item.Verdict]++
		if item.Silent {
			t.Silent++
		}
		if c.Kind == "delete" || c.Kind == "para_delete" {
			t.Deleted++
		}
		t.Items = append(t.Items, item)
	}
	if other != nil {
		out.Topics = append(out.Topics, *other)
	}
	return out, nil
}

func verdictOf(lawyer bool, action, level string) string {
	if lawyer {
		return VerdictLawyer
	}
	if strings.HasPrefix(action, "Согласовано") {
		return VerdictAgreed
	}
	switch level {
	case VerdictReject, VerdictFallback, VerdictAccept:
		return level
	}
	return VerdictNone
}

func shortText(s string) string {
	s = strings.Join(strings.Fields(s), " ")
	if utf8.RuneCountInString(s) <= RoundTextRunes {
		return s
	}
	r := []rune(s)
	return string(r[:RoundTextRunes-1]) + "…"
}
