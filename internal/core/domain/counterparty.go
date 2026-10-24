package core_domain

import (
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

// MaxCounterpartyName — предел названия контрагента.
const MaxCounterpartyName = 255

// NoCounterparty — контрагент для договоров, у которых он не указан (в том числе загруженных до появления контрагентов).
const NoCounterparty = "Без контрагента"

// Counterparty — контрагент: компания, с которой идут переговоры. У него договоры, у договора — раунды.
type Counterparty struct {
	ID        int
	UserID    int
	Name      string
	INN       string
	Dir       string // папка на диске: имя внутри корня хранилища; пусто — файлы не сохраняются
	CreatedAt time.Time
}

// CounterpartySummary — контрагент в списке: сколько у него договоров и раундов и когда была последняя правка.
type CounterpartySummary struct {
	Counterparty
	Contracts int
	Rounds    int
	LastAt    time.Time
}

// CounterpartyView — страница контрагента: он сам и его договоры (недавние — первыми).
type CounterpartyView struct {
	Counterparty CounterpartySummary
	Projects     []ProjectSummary
}

// CounterpartyName — название контрагента: слова через один пробел; пусто — «Без контрагента».
func CounterpartyName(entered string) (string, error) {
	name := strings.Join(strings.Fields(entered), " ")
	if name == "" {
		return NoCounterparty, nil
	}
	if utf8.RuneCountInString(name) > MaxCounterpartyName {
		return "", fmt.Errorf("название контрагента длиннее %d символов: %w", MaxCounterpartyName, core_errors.ErrInvalidArgument)
	}
	return name, nil
}

// CounterpartyINN — ИНН контрагента: пусто или 10 (организация) / 12 (предприниматель) цифр.
func CounterpartyINN(entered string) (string, error) {
	inn := strings.TrimSpace(entered)
	if inn == "" {
		return "", nil
	}
	if len(inn) != 10 && len(inn) != 12 {
		return "", fmt.Errorf("ИНН должен состоять из 10 или 12 цифр: %w", core_errors.ErrInvalidArgument)
	}
	for _, c := range inn {
		if c < '0' || c > '9' {
			return "", fmt.Errorf("ИНН должен состоять из 10 или 12 цифр: %w", core_errors.ErrInvalidArgument)
		}
	}
	return inn, nil
}

// DetectedParty — сторона договора по преамбуле.
type DetectedParty struct {
	Role string
	Name string
	INN  string
}

// DetectedParties — стороны договора и контрагент (сторона, не совпавшая с вашей компанией); Counterparty == nil, если нашу
// сторону определить не удалось: юрист выбирает контрагента сам.
type DetectedParties struct {
	Parties      []DetectedParty
	Counterparty *DetectedParty
}
