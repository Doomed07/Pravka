package core_domain

import (
	"strings"
	"testing"
)

func rc(id, fp, clause, topic, before, after string) RoundChange {
	return RoundChange{ID: id, Fingerprint: fp, Clause: clause, Topic: topic, Kind: "replace", Before: before, After: after}
}

func TestCompareRounds(t *testing.T) {
	round1 := RoundSource{ReviewID: 10, Round: 1,
		Changes: []RoundChange{
			rc("E001", "fp-adv10", "2.2", "порядок и сроки оплаты", "30%", "10%"),
			rc("E002", "fp-term", "3.1", "сроки исполнения", "30 дней", "10 дней"),
			rc("E003", "fp-pen", "5.1", "неустойка и штрафы", "0,1%", "0,01%"),
			rc("E004", "fp-misc", "9.9", "прочее", "а", "б"),
		},
		Decisions: map[string]ReviewChoice{"E001": {ChangeID: "E001", Choice: ChoiceReject}, "E003": {ChangeID: "E003", Choice: ChoiceCounter, Text: "0,05%"}}}
	round2 := RoundSource{ReviewID: 11, Round: 2,
		Changes: []RoundChange{
			rc("E001", "fp-adv10", "2.2", "порядок и сроки оплаты", "30%", "10%"),
			rc("E002", "fp-pen2", "5.1", "неустойка и штрафы", "0,1%", "0,02%"),
			rc("E003", "fp-gone", "7.7", "разрешение споров", "Москва", "Казань"),
		},
		Decisions: map[string]ReviewChoice{"E001": {ChangeID: "E001", Choice: ChoiceReject}, "E003": {ChangeID: "E003", Choice: ChoiceAccept}}}

	cur := []RoundChange{
		rc("E001", "fp-adv10", "2.2", "порядок и сроки оплаты", "30%", "10%"),  // та же правка: есть в раундах 1 и 2
		rc("E002", "fp-term", "3.1", "сроки исполнения", "30 дней", "10 дней"), // та же правка, но только в раунде 1
		rc("E003", "fp-pen3", "5.1", "неустойка и штрафы", "0,1%", "0,03%"),    // тот же пункт и тема, значение другое
		rc("E004", "fp-new", "4.4", "приёмка и качество", "5", "20"),           // раньше не было
		rc("E005", "fp-misc2", "9.9", "прочее", "а", "в"),                      // «прочее» не даёт возвращения
		rc("E006", "fp-notopic", "6.6", "", "x", "y"),                          // без темы тоже
	}
	got := CompareRounds(cur, []RoundSource{round1, round2})
	if len(got.Links) != len(cur) {
		t.Fatalf("links = %d, want %d", len(got.Links), len(cur))
	}
	by := map[string]RoundLink{}
	for _, l := range got.Links {
		by[l.ChangeID] = l
	}

	if l := by["E001"]; l.Relation != RelationRepeat || l.Round != 2 || l.ReviewID != 11 || l.PastChangeID != "E001" ||
		l.Decision != ChoiceReject {
		t.Errorf("E001 (ближайший раунд) = %+v", l)
	}
	if l := by["E002"]; l.Relation != RelationRepeat || l.Round != 1 || l.ReviewID != 10 || l.Decision != "" {
		t.Errorf("E002 (только раунд 1, решения нет) = %+v", l)
	}
	if l := by["E003"]; l.Relation != RelationReturned || l.Round != 2 || l.PastChangeID != "E002" || l.PastAfter != "0,02%" {
		t.Errorf("E003 (вернулся к пункту, ближайший раунд) = %+v", l)
	}
	for _, id := range []string{"E004", "E005", "E006"} {
		if by[id].Relation != RelationNew || by[id].ReviewID != 0 {
			t.Errorf("%s должна быть новой: %+v", id, by[id])
		}
	}
	if got.Count(RelationRepeat) != 2 || got.Count(RelationReturned) != 1 || got.Count(RelationNew) != 3 {
		t.Errorf("counts repeat/returned/new = %d/%d/%d", got.Count(RelationRepeat), got.Count(RelationReturned), got.Count(RelationNew))
	}

	// снято — только из последнего прошлого раунда; к E002 раунда 2 привязана E003 текущего, к E001 — E001
	if len(got.Closed) != 1 || got.Closed[0].ChangeID != "E003" || got.Closed[0].Round != 2 || got.Closed[0].Decision != ChoiceAccept ||
		got.Closed[0].Clause != "7.7" {
		t.Errorf("closed = %+v", got.Closed)
	}

	// «тот же пункт» — это и номер пункта, и тема: другая тема или другой пункт возвращением не считаются
	past := []RoundSource{{ReviewID: 1, Round: 1, Changes: []RoundChange{
		rc("E001", "fp-a", "2.2", "порядок и сроки оплаты", "30%", "10%"),
		rc("E002", "fp-b", "", "порядок и сроки оплаты", "x", "y"),
		rc("E003", "fp-c", "4.1", "", "x", "y")}}}
	for _, c := range []RoundChange{
		rc("E001", "fp-1", "2.2", "сроки исполнения", "30", "10"),         // тот же пункт, другая тема
		rc("E002", "fp-2", "2.3", "порядок и сроки оплаты", "30%", "15%"), // та же тема, другой пункт
		rc("E003", "fp-3", "", "порядок и сроки оплаты", "x", "z"),        // номера пункта нет ни у той, ни у этой
		rc("E004", "fp-4", "4.1", "", "x", "z"),                           // темы нет ни у той, ни у этой
	} {
		if l := CompareRounds([]RoundChange{c}, past).Links[0]; l.Relation != RelationNew {
			t.Errorf("%+v: не возвращение, а %+v", c, l)
		}
	}
	if l := CompareRounds([]RoundChange{rc("E001", "fp-1", "2.2", "порядок и сроки оплаты", "30%", "15%")}, past).Links[0]; l.Relation != RelationReturned {
		t.Errorf("тот же пункт и тема, другое значение: %+v", l)
	}

	// первый раунд проекта: сравнивать не с чем
	first := CompareRounds(cur, nil)
	if first.Count(RelationNew) != len(cur) || len(first.Closed) != 0 {
		t.Errorf("первый раунд = %+v", first)
	}
	// у одной из правок нет отпечатка: «та же правка» без него не устанавливается
	noFP := CompareRounds([]RoundChange{rc("E001", "", "2.2", "порядок и сроки оплаты", "30%", "10%")},
		[]RoundSource{{ReviewID: 1, Round: 1, Changes: []RoundChange{rc("E001", "", "2.2", "порядок и сроки оплаты", "30%", "10%")}}})
	if noFP.Links[0].Relation == RelationRepeat {
		t.Errorf("без отпечатка нельзя считать повтором: %+v", noFP.Links[0])
	}
}

func TestParseRoundChanges(t *testing.T) {
	got, err := ParseRoundChanges([]byte(`[
	{"id":"E001","fingerprint":"a","clause":"2.2","topic":"оплата","kind":"replace","before":"30%","after":"10%","materiality":"высокая"},
	{"id":"E002","fingerprint":"b","kind":"comment","after":"Просим","materiality":"средняя"},
	{"id":"E003","fingerprint":"c","kind":"replace","before":"собственность","after":"собсвенность","materiality":"техническая"},
	{"id":"E004","fingerprint":"d","clause":"3.5","topic":"приёмка","kind":"para_insert","after":"  ` + strings.Repeat("слово ", 40) + `","materiality":"средняя"}]`))
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0].ID != "E001" || got[1].ID != "E004" {
		t.Fatalf("комментарии и технические правки в сравнение не входят: %+v", got)
	}
	if got[0].Fingerprint != "a" || got[0].Before != "30%" || len([]rune(got[1].After)) != RoundTextRunes {
		t.Errorf("поля: %+v", got)
	}
	if _, err := ParseRoundChanges([]byte(`не json`)); err == nil {
		t.Error("broken changes: want error")
	}
}

func TestProjectName(t *testing.T) {
	for _, c := range []struct{ entered, file, want string }{
		{"  Поставка   ООО «Омега»  ", "x.docx", "Поставка ООО «Омега»"},
		{"", "Договор поставки_v3.DOCX", "Договор поставки_v3"},
		{"", "Приложение 2.pdf", "Приложение 2"},
		{"", "Договор.ODT", "Договор"},
		{"", ".docx", "Договор"},
		{"", "", "Договор"},
	} {
		got, err := ProjectName(c.entered, c.file)
		if err != nil || got != c.want {
			t.Errorf("ProjectName(%q, %q) = %q, %v; want %q", c.entered, c.file, got, err, c.want)
		}
	}
	if _, err := ProjectName(strings.Repeat("я", MaxProjectName+1), "x.docx"); err == nil {
		t.Error("введённое название длиннее предела: want error")
	}
	if got, err := ProjectName("", strings.Repeat("я", 300)+".docx"); err != nil || len([]rune(got)) != MaxProjectName {
		t.Errorf("длинное имя файла обрезается: %d, %v", len([]rune(got)), err)
	}
}
