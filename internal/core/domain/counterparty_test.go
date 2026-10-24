package core_domain

import (
	"errors"
	"strings"
	"testing"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func TestCounterpartyName(t *testing.T) {
	for in, want := range map[string]string{
		"  ООО   «Ромашка» ": "ООО «Ромашка»",
		"":                   NoCounterparty,
		"  \n ":              NoCounterparty,
	} {
		if got, err := CounterpartyName(in); err != nil || got != want {
			t.Errorf("CounterpartyName(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	if _, err := CounterpartyName(strings.Repeat("я", MaxCounterpartyName+1)); !errors.Is(err, core_errors.ErrInvalidArgument) {
		t.Errorf("слишком длинное название: err = %v", err)
	}
}

func TestCounterpartyINN(t *testing.T) {
	for _, ok := range []string{"", " 7701234567 ", "770123456789"} {
		if _, err := CounterpartyINN(ok); err != nil {
			t.Errorf("CounterpartyINN(%q): %v", ok, err)
		}
	}
	for _, bad := range []string{"123", "77012345678", "77012345ab", "7701 234567"} {
		if _, err := CounterpartyINN(bad); !errors.Is(err, core_errors.ErrInvalidArgument) {
			t.Errorf("CounterpartyINN(%q): want invalid argument, got %v", bad, err)
		}
	}
}
