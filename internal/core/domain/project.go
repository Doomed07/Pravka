package core_domain

import (
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

// MaxProjectName — предел названия договора (проекта).
const MaxProjectName = 255

// Project — договор, по которому идут переговоры. Его разборы — раунды: номер раунда — порядок разборов по времени.
type Project struct {
	ID               int
	UserID           int
	Name             string
	CreatedAt        time.Time
	CounterpartyID   int
	CounterpartyName string
	Dir              string // путь папки договора на диске («Контрагент/Договор»); пусто — файлы не сохраняются
}

// ProjectSummary — договор в списке: сколько раундов и за какую роль и по какому плейбуку разбирали последний.
type ProjectSummary struct {
	Project
	Rounds       int
	LastReviewID int
	LastAt       time.Time
	Playbook     string
	PlaybookName string
	OurRole      string
	ContractType string
}

// ProjectName — название нового договора: введённое юристом или, если пусто, имя файла контрагента без «.docx», «.odt» или «.pdf».
func ProjectName(entered, theirsFile string) (string, error) {
	name := strings.Join(strings.Fields(entered), " ")
	if name == "" {
		name = strings.Join(strings.Fields(theirsFile), " ")
		for _, ext := range []string{".docx", ".odt", ".pdf"} {
			if len(name) >= len(ext) && strings.EqualFold(name[len(name)-len(ext):], ext) {
				name = strings.TrimSpace(name[:len(name)-len(ext)])
				break
			}
		}
	}
	if name == "" {
		name = "Договор"
	}
	if utf8.RuneCountInString(name) > MaxProjectName {
		if entered != "" {
			return "", fmt.Errorf("название договора длиннее %d символов: %w", MaxProjectName, core_errors.ErrInvalidArgument)
		}
		name = string([]rune(name)[:MaxProjectName])
	}
	return name, nil
}

// ProjectRound — раунд договора: разбор с правками и решениями юриста по ним (для сравнения раундов).
type ProjectRound struct {
	ReviewID   int
	Round      int
	CreatedAt  time.Time
	TheirsName string
	BaseName   string
	Changes    []byte // JSON: список правок разбора
	Choices    []ReviewChoice
}

// ReviewRounds — как разбор связан с прошлыми раундами своего договора.
type ReviewRounds struct {
	Project      ProjectSummary
	Round        int
	PrevReviewID int // разбор предыдущего раунда; 0 — это первый раунд
	Comparison   RoundComparison
}

// ProjectRoundView — строка истории договора: раунд и что в нём нового по сравнению с прошлыми.
type ProjectRoundView struct {
	ReviewID   int
	Round      int
	CreatedAt  time.Time
	TheirsName string
	BaseName   string
	Total      int // значимых правок (без комментариев и технических)
	New        int
	Repeat     int
	Returned   int
	Closed     int
}

// ProjectView — история договора: раунды от первого к последнему.
type ProjectView struct {
	Project ProjectSummary
	Rounds  []ProjectRoundView
}
