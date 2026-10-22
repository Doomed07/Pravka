package core_http_request

import (
	"errors"
	"net/http/httptest"
	"reflect"
	"testing"
	"time"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

// httptest.NewRequest создаёт *http.Request без реального сервера —
// этого достаточно, чтобы проверить разбор query-параметров.

func TestGetIntQueryParam(t *testing.T) {
	tests := []struct {
		name    string
		url     string
		want    *int
		wantErr bool
	}{
		{name: "missing param", url: "/books", want: nil},
		{name: "empty value", url: "/books?limit=", want: nil},
		{name: "valid int", url: "/books?limit=10", want: new(10)},
		{name: "negative int", url: "/books?limit=-5", want: new(-5)},
		{name: "not a number", url: "/books?limit=abc", wantErr: true},
		{name: "float", url: "/books?limit=1.5", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", tt.url, nil)
			got, gotErr := GetIntQueryParam(r, "limit")

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("GetIntQueryParam() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Fatalf("GetIntQueryParam() failed: %v", gotErr)
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetIntQueryParam() = %v, want %v", deref(got), deref(tt.want))
			}
		})
	}
}

func TestGetStrQueryParam(t *testing.T) {
	tests := []struct {
		name string
		url  string
		want *string
	}{
		{name: "missing param", url: "/books", want: nil},
		{name: "only spaces", url: "/books?title=%20%20", want: nil},
		{name: "value trimmed", url: "/books?title=%20Hobbit%20", want: new("Hobbit")},
		{name: "cyrillic", url: "/books?title=%D0%A5%D0%BE%D0%B1%D0%B1%D0%B8%D1%82", want: new("Хоббит")},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", tt.url, nil)
			got := GetStrQueryParam(r, "title")
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetStrQueryParam() = %v, want %v", deref(got), deref(tt.want))
			}
		})
	}
}

func TestGetReadQueryParam(t *testing.T) {
	tests := []struct {
		name    string
		url     string
		want    *bool
		wantErr bool
	}{
		{name: "missing param", url: "/shelf", want: nil},
		{name: "true", url: "/shelf?read=true", want: new(true)},
		{name: "false", url: "/shelf?read=false", want: new(false)},
		{name: "invalid", url: "/shelf?read=yes", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", tt.url, nil)
			got, gotErr := GetReadQueryParam(r)

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("GetReadQueryParam() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Fatalf("GetReadQueryParam() failed: %v", gotErr)
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetReadQueryParam() = %v, want %v", deref(got), deref(tt.want))
			}
		})
	}
}

func TestGetFromToQueryParam(t *testing.T) {
	tests := []struct {
		name     string
		url      string
		wantFrom *time.Time
		wantTo   *time.Time
		wantErr  bool
	}{
		{name: "missing params", url: "/stats"},
		{
			name:     "both dates",
			url:      "/stats?from=2026-01-01&to=2026-01-31",
			wantFrom: new(time.Date(2026, 1, 1, 0, 0, 0, 0, time.Local)),
			wantTo:   new(time.Date(2026, 1, 31, 0, 0, 0, 0, time.Local)),
		},
		{
			name:     "only from",
			url:      "/stats?from=2026-01-01",
			wantFrom: new(time.Date(2026, 1, 1, 0, 0, 0, 0, time.Local)),
		},
		{name: "invalid from format", url: "/stats?from=01.01.2026", wantErr: true},
		{name: "invalid to date", url: "/stats?to=2026-02-30", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", tt.url, nil)
			gotFrom, gotTo, gotErr := GetFromToQueryParam(r)

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("GetFromToQueryParam() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Fatalf("GetFromToQueryParam() failed: %v", gotErr)
			}
			if !equalTime(gotFrom, tt.wantFrom) || !equalTime(gotTo, tt.wantTo) {
				t.Errorf("GetFromToQueryParam() = (%v, %v), want (%v, %v)",
					deref(gotFrom), deref(gotTo), deref(tt.wantFrom), deref(tt.wantTo))
			}
		})
	}
}

func TestGetIntPathParam(t *testing.T) {
	tests := []struct {
		name    string
		value   string
		want    int
		wantErr bool
	}{
		{name: "valid id", value: "42", want: 42},
		{name: "empty", value: "", wantErr: true},
		{name: "not a number", value: "abc", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", "/users/x", nil)
			// в проде значение кладёт http.ServeMux по шаблону /users/{id};
			// в тесте подставляем его вручную
			r.SetPathValue("id", tt.value)

			got, gotErr := GetIntPathParam(r, "id")

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("GetIntPathParam() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Fatalf("GetIntPathParam() failed: %v", gotErr)
			}
			if got != tt.want {
				t.Errorf("GetIntPathParam() = %d, want %d", got, tt.want)
			}
		})
	}
}

// time.Time сравниваем через Equal, а не ==: == учитывает ещё и
// внутреннее представление (локацию, монотонные часы)
func equalTime(a, b *time.Time) bool {
	if a == nil || b == nil {
		return a == b
	}
	return a.Equal(*b)
}

func deref[T any](p *T) any {
	if p == nil {
		return nil
	}
	return *p
}
