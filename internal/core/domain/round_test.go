package core_domain

import (
	"strings"
	"testing"
	"unicode/utf8"
)

func TestSummarizeRound(t *testing.T) {
	long := strings.Repeat("Поставщик хранит Товар за свой счёт ", 5)
	changes := []byte(`[
	{"id":"E001","kind":"replace","clause":"","topic":"стороны и реквизиты","before":"ИНН 7701234567","after":"ИНН 7709876543",
	 "materiality":"высокая","level":"review","lawyer_decision_needed":true},
	{"id":"E002","kind":"comment","clause":"5.3","topic":"ограничение ответственности","before":"Совокупная ответственность",
	 "after":"Просим исключить ограничение ответственности.","materiality":"средняя","level":"review","lawyer_decision_needed":true},
	{"id":"E003","kind":"delete","clause":"5.3","topic":"ограничение ответственности","before":"не более 10% цены",
	 "materiality":"высокая","level":"reject"},
	{"id":"E004","kind":"replace","clause":"4.2","topic":"","before":"5","after":"7","materiality":"низкая","level":"accept"},
	{"id":"E005","kind":"replace","clause":"2.3","topic":"порядок и сроки оплаты","source":"silent","before":"10 дней",
	 "after":"  30\n дней ","materiality":"высокая","level":"reject"},
	{"id":"E006","kind":"replace","clause":"1.1","topic":"предмет договора","before":"Товаре","after":"товаре",
	 "materiality":"техническая","level":"accept"},
	{"id":"E007","kind":"para_insert","clause":"3.5","topic":"прочее","after":"` + long + `","materiality":"средняя",
	 "level":"fallback"},
	{"id":"E008","kind":"replace","clause":"2.4","topic":"порядок и сроки оплаты","source":"diff","before":"аванс",
	 "after":"постоплата","materiality":"высокая","level":"accept","action":"Согласовано ранее"},
	{"id":"E009","kind":"para_delete","clause":"6.1","topic":"порядок и сроки оплаты","before":"Пени 0,1%","materiality":"средняя","level":"review"}]`)
	got, err := SummarizeRound(changes)
	if err != nil {
		t.Fatal(err)
	}

	var topics []string
	for _, tp := range got.Topics {
		topics = append(topics, tp.Topic)
	}
	// порядок — как правки у движка; без темы и «прочее» — одна группа в конце
	if want := "стороны и реквизиты|ограничение ответственности|порядок и сроки оплаты|прочее"; strings.Join(topics, "|") != want {
		t.Fatalf("topics = %v, want %s", topics, want)
	}
	if got.Technical != 1 {
		t.Errorf("technical = %d, want 1", got.Technical)
	}

	limit := got.Topics[1]
	if limit.Verdicts[VerdictLawyer] != 1 || limit.Verdicts[VerdictReject] != 1 || limit.Deleted != 1 || len(limit.Items) != 2 {
		t.Errorf("ограничение ответственности = %+v", limit)
	}
	if it := limit.Items[0]; it.Kind != "comment" || it.After != "Просим исключить ограничение ответственности." {
		t.Errorf("comment item = %+v", it)
	}

	pay := got.Topics[2]
	if pay.Verdicts[VerdictReject] != 1 || pay.Verdicts[VerdictAgreed] != 1 || pay.Verdicts[VerdictNone] != 1 ||
		pay.Verdicts[VerdictAccept] != 0 {
		t.Errorf("оплата verdicts = %v", pay.Verdicts)
	}
	if pay.Silent != 2 || pay.Deleted != 1 {
		t.Errorf("оплата silent = %d, deleted = %d; want 2 and 1", pay.Silent, pay.Deleted)
	}
	if it := pay.Items[0]; !it.Silent || it.Before != "10 дней" || it.After != "30 дней" || it.ChangeID != "E005" || it.Clause != "2.3" {
		t.Errorf("оплата first item = %+v", it)
	}

	other := got.Topics[3]
	if len(other.Items) != 2 || other.Items[0].ChangeID != "E004" || other.Items[1].ChangeID != "E007" {
		t.Fatalf("прочее = %+v", other.Items)
	}
	if other.Verdicts[VerdictAccept] != 1 || other.Verdicts[VerdictFallback] != 1 {
		t.Errorf("прочее verdicts = %v", other.Verdicts)
	}
	if a := other.Items[1].After; utf8.RuneCountInString(a) != RoundTextRunes || !strings.HasSuffix(a, "…") {
		t.Errorf("long text not shortened: %q", a)
	}
	if got.Topics[0].Verdicts[VerdictLawyer] != 1 {
		t.Errorf("решает юрист важнее уровня правила: %v", got.Topics[0].Verdicts)
	}

	empty, err := SummarizeRound([]byte(`[]`))
	if err != nil || len(empty.Topics) != 0 || empty.Topics == nil {
		t.Errorf("empty = %+v, %v", empty, err)
	}
	if _, err := SummarizeRound([]byte(`не json`)); err == nil {
		t.Error("broken changes: want error")
	}
}

func TestSummarizeRound_ClauseRemarksOfFirstVersion(t *testing.T) {
	got, err := SummarizeRound([]byte(`[{"id":"E001","source":"clause","kind":"para_insert","clause":"4.2","topic":"неустойка и штрафы",
		"after":"Неустойка 1% в день","materiality":"высокая","level":"reject"}]`))
	if err != nil || len(got.Topics) != 1 {
		t.Fatalf("%+v, %v", got, err)
	}
	if it := got.Topics[0].Items[0]; it.Kind != "clause" || it.Silent || it.Verdict != VerdictReject {
		t.Errorf("замечание к положению: %+v", it)
	}
	if got.Topics[0].Deleted != 0 {
		t.Errorf("положение не считается удалением")
	}
}

func TestParseRoundChanges_MarksRemarksOfFirstVersion(t *testing.T) {
	got, err := ParseRoundChanges([]byte(`[
		{"id":"E001","source":"clause","kind":"para_insert","topic":"неустойка и штрафы","after":"Неустойка 1%","materiality":"высокая"},
		{"id":"E002","source":"tracked","kind":"replace","topic":"неустойка и штрафы","before":"0,1%","after":"1%","materiality":"высокая"}]`))
	// замечание остаётся с пометкой Remark (по нему вспоминается ваше решение), но правкой раунда не считается
	if err != nil || len(got) != 2 || !got[0].Remark || got[1].Remark {
		t.Fatalf("замечание помечено, правка контрагента — нет: %+v, %v", got, err)
	}
	if cmp := CompareRounds(got, nil); len(cmp.Links) != 1 || cmp.Links[0].ChangeID != "E002" {
		t.Errorf("в раундах сравниваются только правки контрагента: %+v", cmp.Links)
	}
}
