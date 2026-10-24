package filestore

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSafeName(t *testing.T) {
	cases := map[string]string{
		`ООО «Ромашка»`:        "ООО «Ромашка»",
		"  ИП   Иванов  И.И. ": "ИП Иванов И.И.",
		`../../etc/passwd`:     "etc passwd",
		`a/b\c:d*e?f"g<h>i|j`:  "a b c d e f g h i j",
		"..":                   "Без названия",
		"":                     "Без названия",
		"Договор\n№ 5":         "Договор № 5",
		".hidden":              "hidden",
	}
	for in, want := range cases {
		if got := SafeName(in); got != want {
			t.Errorf("SafeName(%q) = %q, want %q", in, got, want)
		}
	}
	if n := len([]rune(SafeName(strings.Repeat("я", 500)))); n != MaxNameRunes {
		t.Errorf("длинное имя: %d знаков, want %d", n, MaxNameRunes)
	}
}

func TestExt(t *testing.T) {
	for in, want := range map[string]string{"a.DOCX": ".docx", "b.odt": ".odt", "c.PDF": ".pdf", "d.exe": ".docx", "e": ".docx"} {
		if got := Ext(in); got != want {
			t.Errorf("Ext(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestSaveWritesIntoRoundFolderAndOverwrites(t *testing.T) {
	root := t.TempDir()
	s := New(root)
	if err := s.Save("Ромашка/Договор поставки", 2, TheirsFile+".docx", []byte("one")); err != nil {
		t.Fatal(err)
	}
	if err := s.Save("Ромашка/Договор поставки", 2, TheirsFile+".docx", []byte("two")); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(root, "Ромашка", "Договор поставки", "Раунд 2", "01 Версия контрагента.docx"))
	if err != nil || string(got) != "two" {
		t.Fatalf("file = %q, %v", got, err)
	}
	entries, _ := os.ReadDir(filepath.Join(root, "Ромашка", "Договор поставки", "Раунд 2"))
	if len(entries) != 1 {
		t.Errorf("в папке раунда лишние файлы: %v", entries)
	}
}

func TestSaveRefusesToEscapeTheRoot(t *testing.T) {
	root := t.TempDir()
	s := New(filepath.Join(root, "contracts"))
	for _, rel := range []string{"../evil", "a/../../evil", "/../x"} {
		if err := s.Save(rel, 1, "f.docx", []byte("x")); err == nil {
			t.Errorf("Save(%q): want error", rel)
		}
	}
	if _, err := os.Stat(filepath.Join(root, "evil")); err == nil {
		t.Error("файл записан за пределами хранилища")
	}
}

func TestDisabledStoreAndEmptyPathDoNothing(t *testing.T) {
	if err := New("").Save("a/b", 1, "f.docx", []byte("x")); err != nil {
		t.Errorf("выключенное хранилище: %v", err)
	}
	root := t.TempDir()
	if err := New(root).Save("", 1, "f.docx", []byte("x")); err != nil {
		t.Errorf("пустой путь: %v", err)
	}
	if entries, _ := os.ReadDir(root); len(entries) != 0 {
		t.Errorf("записано при пустом пути: %v", entries)
	}
}
