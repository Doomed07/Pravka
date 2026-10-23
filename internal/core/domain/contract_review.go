package core_domain

import (
	"fmt"
	"path/filepath"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

// MaxUploadBytes — предел размера одного docx.
const MaxUploadBytes = 30 << 20

// ContractReview — один разбор правок контрагента: что загрузили и что получилось.
// Тяжёлые части (HTML-отчёт, Excel, список правок) хранятся отдельно и отдаются по запросу.
type ContractReview struct {
	ID        int
	UserID    int
	CreatedAt time.Time

	TheirsName   string
	BaseName     string
	Playbook     string
	PlaybookName string
	OurRole      string
	Side         string
	Counts       map[string]int
	Warnings     []string
}

// ReviewFiles — тяжёлые результаты разбора.
type ReviewFiles struct {
	ReportHTML []byte
	ReportXLSX []byte
	Changes    []byte // JSON
	Document   []byte // JSON: единая версия договора (абзацы с правками)
	Unified    []byte // docx: единая версия с примечаниями; у разборов до версии 0.3 пусто
}

// UploadedFile — docx из формы.
type UploadedFile struct {
	Name string
	Data []byte
}

// ReviewRequest — что пользователь отправил на разбор.
type ReviewRequest struct {
	Theirs      UploadedFile
	Base        *UploadedFile
	Playbook    string
	OurAuthors  string
	Company     string
	ConfirmRole string
}

// Validate проверяет запрос до обращения к движку: дешёвые ошибки ловим сразу.
func (r *ReviewRequest) Validate() error {
	if err := validateDocx(r.Theirs, "версия контрагента"); err != nil {
		return err
	}
	if r.Base != nil {
		if err := validateDocx(*r.Base, "наша версия"); err != nil {
			return err
		}
	}
	for name, v := range map[string]string{"playbook": r.Playbook, "our_authors": r.OurAuthors, "company": r.Company,
		"confirm_role": r.ConfirmRole} {
		if utf8.RuneCountInString(v) > 500 {
			return fmt.Errorf("поле %s длиннее 500 символов: %w", name, core_errors.ErrInvalidArgument)
		}
	}
	return nil
}

func validateDocx(f UploadedFile, what string) error {
	if len(f.Data) == 0 {
		return fmt.Errorf("%s: файл не загружен: %w", what, core_errors.ErrInvalidArgument)
	}
	if len(f.Data) > MaxUploadBytes {
		return fmt.Errorf("%s: файл больше 30 МБ: %w", what, core_errors.ErrInvalidArgument)
	}
	if !strings.EqualFold(filepath.Ext(f.Name), ".docx") {
		return fmt.Errorf("%s: нужен файл .docx: %w", what, core_errors.ErrInvalidArgument)
	}
	if len(f.Data) < 4 || string(f.Data[:2]) != "PK" { // docx — это zip
		return fmt.Errorf("%s: файл не похож на docx: %w", what, core_errors.ErrInvalidArgument)
	}
	return nil
}

// CleanFileName оставляет от имени файла только последнюю часть пути и ограничивает длину.
func CleanFileName(name string) string {
	name = strings.ReplaceAll(name, "\\", "/")
	if i := strings.LastIndex(name, "/"); i >= 0 {
		name = name[i+1:]
	}
	name = strings.TrimSpace(name)
	if utf8.RuneCountInString(name) > 200 {
		r := []rune(name)
		name = string(r[:200])
	}
	return name
}

// Playbook — плейбук, доступный движку.
type Playbook struct {
	Key  string
	Name string
	Role string
}

// Решения юриста по правке в пошаговом просмотре.
const (
	ChoiceAccept  = "accept"  // принять правку контрагента
	ChoiceReject  = "reject"  // отклонить
	ChoiceCounter = "counter" // встречная редакция: текст пишет юрист
)

// MaxChoiceText — предел текста встречной редакции.
const MaxChoiceText = 5000

// ReviewChoice — решение юриста по одной правке разбора. Пустой Choice — решение снято.
type ReviewChoice struct {
	ChangeID string
	Choice   string
	Text     string
}

// Validate: номер правки как в разборе (E001, S002), известный выбор, текст не длиннее предела.
func (c ReviewChoice) Validate() error {
	if !changeIDRe.MatchString(c.ChangeID) {
		return fmt.Errorf("номер правки %q: %w", c.ChangeID, core_errors.ErrInvalidArgument)
	}
	switch c.Choice {
	case "", ChoiceAccept, ChoiceReject, ChoiceCounter:
	default:
		return fmt.Errorf("неизвестное решение %q: %w", c.Choice, core_errors.ErrInvalidArgument)
	}
	if utf8.RuneCountInString(c.Text) > MaxChoiceText {
		return fmt.Errorf("текст встречной редакции длиннее %d символов: %w", MaxChoiceText, core_errors.ErrInvalidArgument)
	}
	return nil
}

var changeIDRe = regexp.MustCompile(`^[A-Z]\d{3,5}$`)
