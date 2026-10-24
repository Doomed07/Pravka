package core_domain

import "testing"

func TestOurParagraphs(t *testing.T) {
	doc := []byte(`[
	{"index":0,"clause":"","segments":[{"k":"equal","t":"ООО «Омега Снаб», именуемое в дальнейшем «Поставщик», в лице директора"}]},
	{"index":3,"clause":"1","segments":[{"k":"equal","t":"Предмет договора"}]},
	{"index":7,"clause":"2.1","segments":[{"k":"equal","t":"Общая стоимость Товара составляет "},{"k":"del","t":"2 400 000"},
	 {"k":"ins","t":"2 000 000"},{"k":"equal","t":" рублей,  в том числе НДС."}]},
	{"index":-1,"clause":"5.4","segments":[{"k":"silent_del","t":"Поставщик не возмещает Покупателю упущенную выгоду ни при каких условиях."}]},
	{"index":9,"clause":"8.1","segments":[{"k":"equal","t":"Споры разрешаются в Арбитражном суде "},{"k":"silent_del","t":"города Москвы"},
	 {"k":"silent_ins","t":"Новосибирской области"},{"k":"equal","t":"."}]}]`)
	got, err := OurParagraphs(doc)
	if err != nil {
		t.Fatal(err)
	}
	want := []DocParagraph{
		{7, "2.1", "Общая стоимость Товара составляет 2 400 000 рублей, в том числе НДС."},
		{-4, "5.4", "Поставщик не возмещает Покупателю упущенную выгоду ни при каких условиях."},
		{9, "8.1", "Споры разрешаются в Арбитражном суде города Москвы."},
	}
	if len(got) != len(want) {
		t.Fatalf("got %+v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("paragraph %d = %+v, want %+v", i, got[i], want[i])
		}
	}
	if _, err := OurParagraphs([]byte(`не json`)); err == nil {
		t.Error("broken document: want error")
	}
}
