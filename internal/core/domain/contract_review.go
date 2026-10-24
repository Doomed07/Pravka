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

// MaxUploadBytes — предел размера одного файла договора.
const MaxUploadBytes = 30 << 20

// ContractReview — один разбор правок контрагента: что загрузили и что получилось.
// Тяжёлые части (HTML-отчёт, Excel, список правок) хранятся отдельно и отдаются по запросу.
type ContractReview struct {
	ID        int
	UserID    int
	CreatedAt time.Time

	ProjectID        int // договор (проект), раундом которого стал разбор
	ProjectName      string
	CounterpartyID   int
	CounterpartyName string
	ProjectDir       string // только при создании нового договора: путь его папки на диске
	Round            int    // номер раунда в проекте: порядок разборов по времени
	HasDocx          bool   // есть единая версия в Word: только если файл контрагента — .docx
	TheirsName       string
	BaseName         string
	Playbook         string
	PlaybookName     string
	OurRole          string
	ContractType     string // тип договора по плейбуку: supply, services…
	Side             string
	Counts           map[string]int
	Warnings         []string
}

// ReviewFiles — тяжёлые результаты разбора.
type ReviewFiles struct {
	ReportHTML []byte
	ReportXLSX []byte
	Changes    []byte // JSON
	Document   []byte // JSON: единая версия договора (абзацы с правками)
	Unified    []byte // docx: единая версия с примечаниями; у разборов до версии 0.3 пусто
}

// UploadedFile — файл договора из формы (.docx, .odt или PDF).
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
	ProjectID   int    // 0 — новый договор; иначе очередной раунд существующего
	ProjectName string // название нового договора; пусто — имя файла контрагента

	// Контрагент нового договора: CounterpartyID — существующий; иначе по названию (ищется или создаётся); пусто — «Без контрагента».
	CounterpartyID   int
	CounterpartyName string
	CounterpartyINN  string

	// FirstVersion — первая версия нового договора, как прислал контрагент: правок в ней нет, поэтому положения
	// проверяются по плейбуку. Только для нового договора (ProjectID == 0).
	FirstVersion bool
}

// Validate проверяет запрос до обращения к движку: дешёвые ошибки ловим сразу.
func (r *ReviewRequest) Validate() error {
	if err := validateDocument(r.Theirs, "версия контрагента"); err != nil {
		return err
	}
	if r.Base != nil {
		if err := validateDocument(*r.Base, "наша версия"); err != nil {
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

// Форматы файлов: .docx и .odt — zip («PK»), PDF начинается с «%PDF-». Формат движок определяет по содержимому.
var documentFormats = map[string]string{".docx": "PK", ".odt": "PK", ".pdf": "%PDF-"}

// SupportedFormats — для сообщений об ошибках.
const SupportedFormats = ".docx, .odt или PDF с текстом"

// validateDocument — дешёвая проверка файла до обращения к движку: размер, расширение, сигнатура.
func validateDocument(f UploadedFile, what string) error {
	if len(f.Data) == 0 {
		return fmt.Errorf("%s: файл не загружен: %w", what, core_errors.ErrInvalidArgument)
	}
	if len(f.Data) > MaxUploadBytes {
		return fmt.Errorf("%s: файл больше 30 МБ: %w", what, core_errors.ErrInvalidArgument)
	}
	ext := strings.ToLower(filepath.Ext(f.Name))
	signature, ok := documentFormats[ext]
	if !ok {
		return fmt.Errorf("%s: нужен файл %s: %w", what, SupportedFormats, core_errors.ErrInvalidArgument)
	}
	if !strings.HasPrefix(string(f.Data[:min(len(f.Data), len(signature))]), signature) {
		return fmt.Errorf("%s: файл не похож на %s: %w", what, ext, core_errors.ErrInvalidArgument)
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
	ChoiceReply   = "reply"   // ответ на комментарий контрагента: текст пишет юрист
	ChoiceEdit    = "edit"    // правка текста абзаца на сайте; номер «P<абзац>», в Text — новый текст абзаца целиком
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
	case "", ChoiceAccept, ChoiceReject, ChoiceCounter, ChoiceReply:
		if strings.HasPrefix(c.ChangeID, "P") && c.Choice != "" || strings.HasPrefix(c.ChangeID, "A") && c.Choice != "" {
			return fmt.Errorf("номер %q — правка текста абзаца, у неё только решение %q: %w", c.ChangeID, ChoiceEdit, core_errors.ErrInvalidArgument)
		}
		if strings.HasPrefix(c.ChangeID, "X") && c.Choice != "" && c.Choice != ChoiceReject {
			return fmt.Errorf("номер %q — удаление абзаца: только решение %q: %w", c.ChangeID, ChoiceReject, core_errors.ErrInvalidArgument)
		}
	case ChoiceEdit:
		if !(strings.HasPrefix(c.ChangeID, "P") || strings.HasPrefix(c.ChangeID, "A")) || strings.TrimSpace(c.Text) == "" {
			return fmt.Errorf("правка абзаца: номер вида P012 или A012 и непустой текст: %w", core_errors.ErrInvalidArgument)
		}
	default:
		return fmt.Errorf("неизвестное решение %q: %w", c.Choice, core_errors.ErrInvalidArgument)
	}
	if utf8.RuneCountInString(c.Text) > MaxChoiceText {
		return fmt.Errorf("текст длиннее %d символов: %w", MaxChoiceText, core_errors.ErrInvalidArgument)
	}
	return nil
}

var changeIDRe = regexp.MustCompile(`^[A-Z]\d{3,5}$`)

// Precedent — «как решали раньше»: похожая правка из прошлого разбора того же юриста (тот же тип договора и наша роль)
// и его решение по ней. Только подсказка: решение по текущей правке принимает плейбук и юрист.
type Precedent struct {
	ChangeID     string // правка текущего разбора, к которой подобрана подсказка
	ReviewID     int
	PastChangeID string // номер правки в прошлом разборе
	TheirsName   string
	CreatedAt    time.Time
	Clause       string
	Topic        string
	Before       string
	After        string
	Choice       string  // решение юриста: accept, reject или counter
	Text         string  // текст встречной редакции
	Same         bool    // та же правка: «было» и «стало» совпадают
	Semantic     bool    // найдена по смыслу (вектор), а не по словам
	Score        float64 // похожесть от 0 до 1
}

// MaxPrecedents — сколько прошлых решений показывать к одной правке.
const MaxPrecedents = 3

// SemanticPrecedentMaxDistance — «как решали раньше» по смыслу: дальше этого прошлая правка не показывается.
// На учебных договорах та же правка — не дальше 0,134 (199 из 199), правка другого пункта той же темы и стороны —
// не ближе 0,168.
const SemanticPrecedentMaxDistance = 0.15
