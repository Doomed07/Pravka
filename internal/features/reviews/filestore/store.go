// Package filestore складывает файлы раундов в папки на диске: «Контрагент / Договор / Раунд N / файл».
// Папки нужны юристу, чтобы видеть договоры в Finder; источник правды — база, сбой диска разбор не ломает.
package filestore

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unicode"
	"unicode/utf8"
)

// MaxNameRunes — предел имени папки.
const MaxNameRunes = 100

// Имена файлов в папке раунда: номер задаёт порядок — сначала присланное, затем наш ответ.
const (
	TheirsFile = "01 Версия контрагента"
	AnswerFile = "02 Наша версия с ответами"
)

// Store — корень хранилища. Пустой корень — хранилище выключено: все операции ничего не делают.
type Store struct {
	root string
}

func New(root string) *Store { return &Store{root: strings.TrimSpace(root)} }

func (s *Store) Enabled() bool { return s != nil && s.root != "" }

// SafeName — имя папки из названия: без разделителей путей, служебных и управляющих знаков, без точек в начале (имя «..» и скрытые папки исключены).
func SafeName(name string) string {
	var b strings.Builder
	for _, r := range strings.Join(strings.Fields(name), " ") {
		switch {
		case unicode.IsControl(r), strings.ContainsRune(`/\:*?"<>|`, r):
			b.WriteRune(' ')
		default:
			b.WriteRune(r)
		}
	}
	out := strings.TrimLeft(strings.Join(strings.Fields(b.String()), " "), ". ")
	if utf8.RuneCountInString(out) > MaxNameRunes {
		out = strings.TrimSpace(string([]rune(out)[:MaxNameRunes]))
	}
	if out == "" {
		return "Без названия"
	}
	return out
}

// Ext — расширение сохраняемого файла: только .docx, .odt или .pdf (по имени загрузки); иное — .docx.
func Ext(uploadName string) string {
	switch e := strings.ToLower(filepath.Ext(uploadName)); e {
	case ".docx", ".odt", ".pdf":
		return e
	}
	return ".docx"
}

// RoundDir — папка раунда внутри корня; rel — путь договора из базы («Контрагент/Договор»).
func (s *Store) RoundDir(rel string, round int) (string, error) {
	if !s.Enabled() {
		return "", nil
	}
	if round < 1 {
		return "", fmt.Errorf("номер раунда %d", round)
	}
	dir := filepath.Join(s.root, filepath.FromSlash(rel), fmt.Sprintf("Раунд %d", round))
	root, err := filepath.Abs(s.root)
	if err != nil {
		return "", err
	}
	abs, err := filepath.Abs(dir)
	if err != nil {
		return "", err
	}
	if sub, err := filepath.Rel(root, abs); err != nil || sub == "." || strings.HasPrefix(sub, "..") {
		return "", fmt.Errorf("путь %q выходит за папку хранилища", rel)
	}
	return abs, nil
}

// Save записывает файл в папку раунда (перезаписывает). Пустой rel — у договора нет папки: ничего не делает.
func (s *Store) Save(rel string, round int, name string, data []byte) error {
	if !s.Enabled() || strings.TrimSpace(rel) == "" {
		return nil
	}
	dir, err := s.RoundDir(rel, round)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return fmt.Errorf("создать папку раунда: %w", err)
	}
	tmp, err := os.CreateTemp(dir, ".tmp-*")
	if err != nil {
		return fmt.Errorf("создать файл: %w", err)
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return fmt.Errorf("записать файл: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmp.Name(), 0o640); err != nil {
		return err
	}
	if err := os.Rename(tmp.Name(), filepath.Join(dir, name)); err != nil {
		return fmt.Errorf("записать файл: %w", err)
	}
	return nil
}
