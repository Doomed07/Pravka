package core_domain

import (
	"errors"
	"testing"
	"time"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func TestNormalizePagination(t *testing.T) {
	tests := []struct {
		name       string
		limit      *int
		offset     *int
		wantLimit  int
		wantOffset int
		wantErr    bool
	}{
		{
			name:       "defaults when not provided",
			wantLimit:  DefaultLimit,
			wantOffset: 0,
		},
		{
			name:       "custom values",
			limit:      new(50),
			offset:     new(10),
			wantLimit:  50,
			wantOffset: 10,
		},
		{
			name:      "limit lower bound",
			limit:     new(1),
			wantLimit: 1,
		},
		{
			name:      "limit upper bound",
			limit:     new(MaxLimit),
			wantLimit: MaxLimit,
		},
		{
			name:    "limit zero",
			limit:   new(0),
			wantErr: true,
		},
		{
			name:    "limit above max",
			limit:   new(MaxLimit + 1),
			wantErr: true,
		},
		{
			name:    "negative offset",
			offset:  new(-1),
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotLimit, gotOffset, gotErr := NormalizePagination(tt.limit, tt.offset)

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("NormalizePagination() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Fatalf("NormalizePagination() failed: %v", gotErr)
			}
			if gotLimit != tt.wantLimit || gotOffset != tt.wantOffset {
				t.Errorf("NormalizePagination() = (%d, %d), want (%d, %d)",
					gotLimit, gotOffset, tt.wantLimit, tt.wantOffset)
			}
		})
	}
}

func TestValidateFromToQuery(t *testing.T) {
	day1 := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	day2 := time.Date(2026, 1, 2, 0, 0, 0, 0, time.UTC)

	tests := []struct {
		name    string
		from    *time.Time
		to      *time.Time
		wantErr bool
	}{
		{name: "both nil"},
		{name: "only from", from: &day1},
		{name: "only to", to: &day1},
		{name: "from before to", from: &day1, to: &day2},
		{name: "from equals to", from: &day1, to: &day1},
		{name: "from after to", from: &day2, to: &day1, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotErr := ValidateFromToQuery(tt.from, tt.to)

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("ValidateFromToQuery() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Errorf("ValidateFromToQuery() failed: %v", gotErr)
			}
		})
	}
}

func TestNormalizeTopQueryParam(t *testing.T) {
	tests := []struct {
		name    string
		top     *int
		want    int
		wantErr bool
	}{
		{name: "default when not provided", want: DefaultTop},
		{name: "lower bound", top: new(5), want: 5},
		{name: "upper bound", top: new(MaxTop), want: MaxTop},
		{name: "below range", top: new(4), wantErr: true},
		{name: "above range", top: new(MaxTop + 1), wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, gotErr := NormalizeTopQueryParam(tt.top)

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("NormalizeTopQueryParam() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Fatalf("NormalizeTopQueryParam() failed: %v", gotErr)
			}
			if got != tt.want {
				t.Errorf("NormalizeTopQueryParam() = %d, want %d", got, tt.want)
			}
		})
	}
}

func TestVectorChange_EmbedText(t *testing.T) {
	cases := []struct {
		c    VectorChange
		want string
	}{
		{VectorChange{Kind: "replace", Topic: "неустойка и штрафы", Context: "0,1%", ContextAfter: "0,5%"}, "неустойка и штрафы. 0,5%"},
		// удаление: условие было в прежнем абзаце
		{VectorChange{Kind: "delete", Topic: "ограничение ответственности", Context: "Не возмещает упущенную выгоду.",
			ContextAfter: ""}, "ограничение ответственности. Не возмещает упущенную выгоду."},
		{VectorChange{Kind: "para_insert", Topic: "прочее", ContextAfter: "Новый пункт."}, "Новый пункт."},
	}
	for _, c := range cases {
		if got := c.c.EmbedText(); got != c.want {
			t.Errorf("EmbedText(%+v) = %q, want %q", c.c, got, c.want)
		}
	}
}
