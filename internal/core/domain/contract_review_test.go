package core_domain

import (
	"errors"
	"strings"
	"testing"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func TestValidateDocument(t *testing.T) {
	zip := []byte("PK\x03\x04data")
	pdf := []byte("%PDF-1.7\n%data")
	cases := []struct {
		name string
		file UploadedFile
		want string // подстрока сообщения; пусто — файл принят
	}{
		{"docx", UploadedFile{Name: "Договор.docx", Data: zip}, ""},
		{"docx в верхнем регистре", UploadedFile{Name: "ДОГОВОР.DOCX", Data: zip}, ""},
		{"odt", UploadedFile{Name: "Договор.odt", Data: zip}, ""},
		{"pdf", UploadedFile{Name: "Договор.pdf", Data: pdf}, ""},
		{"pdf в верхнем регистре", UploadedFile{Name: "Договор.PDF", Data: pdf}, ""},
		{"пустой файл", UploadedFile{Name: "a.docx"}, "не загружен"},
		{"неподдерживаемое расширение", UploadedFile{Name: "a.doc", Data: zip}, ".docx, .odt или PDF"},
		{"без расширения", UploadedFile{Name: "договор", Data: zip}, ".docx, .odt или PDF"},
		{"pdf с содержимым zip", UploadedFile{Name: "a.pdf", Data: zip}, "не похож на .pdf"},
		{"docx с содержимым pdf", UploadedFile{Name: "a.docx", Data: pdf}, "не похож на .docx"},
		{"odt с чужим содержимым", UploadedFile{Name: "a.odt", Data: []byte("hello")}, "не похож на .odt"},
		{"слишком короткий zip", UploadedFile{Name: "a.docx", Data: []byte("P")}, "не похож на .docx"},
		{"слишком большой", UploadedFile{Name: "a.pdf", Data: append([]byte("%PDF-"), make([]byte, MaxUploadBytes)...)}, "больше 30 МБ"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			err := validateDocument(c.file, "версия контрагента")
			if c.want == "" {
				if err != nil {
					t.Fatalf("err = %v, want nil", err)
				}
				return
			}
			if !errors.Is(err, core_errors.ErrInvalidArgument) || !strings.Contains(err.Error(), c.want) || !strings.Contains(err.Error(), "версия контрагента") {
				t.Fatalf("err = %v, want invalid argument with %q", err, c.want)
			}
		})
	}
}

func TestReviewRequest_ValidateChecksBothFiles(t *testing.T) {
	ok := UploadedFile{Name: "a.pdf", Data: []byte("%PDF-1.4")}
	bad := UploadedFile{Name: "b.docx", Data: []byte("hello")}
	if err := (&ReviewRequest{Theirs: ok, Base: &UploadedFile{Name: "b.docx", Data: []byte("PK\x03\x04")}}).Validate(); err != nil {
		t.Fatalf("pdf + docx: %v", err)
	}
	if err := (&ReviewRequest{Theirs: ok, Base: &bad}).Validate(); err == nil || !strings.Contains(err.Error(), "наша версия") {
		t.Fatalf("плохая наша версия: %v", err)
	}
	if err := (&ReviewRequest{Theirs: bad}).Validate(); err == nil || !strings.Contains(err.Error(), "версия контрагента") {
		t.Fatalf("плохая версия контрагента: %v", err)
	}
}
