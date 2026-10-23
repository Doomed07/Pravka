package core_domain

import (
	"errors"
	"strings"
	"testing"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

// Go-конвенция: файл теста лежит рядом с тестируемым кодом и называется
// <имя_файла>_test.go. Пакет обычно тот же самый (core_domain), поэтому
// тест имеет доступ к неэкспортируемым полям/функциям — это удобно для
// юнит-тестов домена.

func TestUser_Validate(t *testing.T) {
	// "Table-driven test": вместо того чтобы писать отдельную func Test...
	// на каждый кейс, описываем кейсы как данные в срезе. Это идиоматичный
	// для Go подход — легко добавлять новые кейсы, не плодя функции.
	tests := []struct {
		name    string // человекочитаемое имя кейса, покажется в выводе go test
		user    User
		wantErr bool // ожидаем ли мы ошибку вообще
	}{
		{
			name: "valid user",
			user: User{
				Username: "book_worm07",
				Email:    "lol@mail.com",
			},
			wantErr: false,
		},
		{
			name: "username too short",
			user: User{
				Username: "ab", // меньше 3 символов — см. user.go:64
				Email:    "lol@mail.com",
			},
			wantErr: true,
		},
		{
			name: "username too long",
			user: User{
				Username: "a123456789012345678901234567890", // 31 символ, лимит — 30
				Email:    "lol@mail.com",
			},
			wantErr: true,
		},
		{
			name: "username with invalid characters",
			user: User{
				Username: "book worm!", // пробел и "!" не разрешены regexp'ом reUsername
				Email:    "lol@mail.com",
			},
			wantErr: true,
		},
		{
			name: "invalid email format",
			user: User{
				Username: "book_worm07",
				Email:    "not-an-email",
			},
			wantErr: true,
		},
		{
			name: "empty email",
			user: User{
				Username: "book_worm07",
				Email:    "",
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		// t.Run создаёт "субтест" — он покажется в выводе отдельной строкой
		// (--- PASS: TestUser_Validate/valid_user), и упавший кейс не
		// прерывает остальные: go test прогонит все кейсы и покажет все фейлы сразу.
		t.Run(tt.name, func(t *testing.T) {
			err := tt.user.Validate()

			if tt.wantErr && err == nil {
				t.Errorf("Validate() expected error, got nil")
			}
			if !tt.wantErr && err != nil {
				t.Errorf("Validate() unexpected error: %v", err)
			}

			// Если ошибка ожидается, дополнительно проверяем, что это
			// именно наш sentinel-тип ошибки (core_errors.ErrInvalidArgument),
			// обёрнутый через %w — так тест ловит не просто "какую-то ошибку",
			// а конкретно ожидаемую семантику (как это делает транспортный
			// слой через errors.Is, чтобы вернуть 400).
			if tt.wantErr && err != nil && !errors.Is(err, core_errors.ErrInvalidArgument) {
				t.Errorf("Validate() error = %v, want wrapped core_errors.ErrInvalidArgument", err)
			}
		})
	}
}

func TestUserPatch_Validate(t *testing.T) {
	tests := []struct {
		name string // description of this test case
		// Named input parameters for receiver constructor.
		username Nullable[string]
		email    Nullable[string]
		wantErr  bool
	}{
		{
			name: "valid username",
			username: Nullable[string]{
				Set:   true,
				Value: new("kek"), // Go 1.26: new(expr) теперь даёт указатель на копию значения
			},
			email: Nullable[string]{
				Set:   true,
				Value: new("Boom09@mail.com"),
			},
			wantErr: false,
		},
		{
			name: "invalid username",
			username: Nullable[string]{
				Set:   true,
				Value: nil,
			},
			email: Nullable[string]{
				Set: false,
			},
			wantErr: true,
		},
		{
			name: "invalid email",
			username: Nullable[string]{
				Set: false,
			},
			email: Nullable[string]{
				Set:   true,
				Value: nil,
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			p := NewUserPatch(tt.username, tt.email)
			gotErr := p.Validate()
			if tt.wantErr {
				if gotErr == nil {
					t.Fatal("Validate() succeeded unexpectedly")
				}
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("Validate() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Errorf("Validate() failed: %v", gotErr)
			}
		})
	}
}

func TestUser_ApplyPatch(t *testing.T) {
	baseUser := User{
		ID:       1,
		Version:  1,
		Username: "book_worm07",
		Email:    "lol@mail.com",
	}

	tests := []struct {
		name     string
		patch    UserPatch
		wantErr  bool
		wantUser User // ожидаемое состояние ПОСЛЕ вызова (используется, только если !wantErr)
	}{
		{
			name: "username updated and normalized",
			patch: NewUserPatch(
				Nullable[string]{Set: true, Value: new("  New_Name  ")}, // с пробелами
				Nullable[string]{Set: false},
			),
			wantErr: false,
			wantUser: User{
				ID:       1,
				Version:  1,
				Username: "New_Name", // normalizeUsername должен обрезать пробелы
				Email:    "lol@mail.com",
			},
		},
		{
			name: "email updated and normalized",
			patch: NewUserPatch(
				Nullable[string]{Set: false},
				Nullable[string]{Set: true, Value: new(" TEST@mail.ru ")},
			),
			wantErr: false,
			wantUser: User{
				ID:       1,
				Version:  1,
				Username: "book_worm07",
				Email:    "test@mail.ru",
			},
		},
		{
			name: "username set to NULL — error, user unchanged",
			patch: NewUserPatch(
				Nullable[string]{Set: true, Value: nil},
				Nullable[string]{Set: false},
			),
			wantErr: true,
			wantUser: User{
				ID:       1,
				Version:  1,
				Username: "book_worm07",
				Email:    "lol@mail.com",
			},
		},
		{
			name: "patched username too short — error, user unchanged",
			patch: NewUserPatch(
				Nullable[string]{Set: true, Value: new("Bo")},
				Nullable[string]{Set: false},
			),
			wantErr: true,
			wantUser: User{
				ID:       1,
				Version:  1,
				Username: "book_worm07",
				Email:    "lol@mail.com",
			},
		},
		{
			name: "email set to NULL — error, user unchanged",
			patch: NewUserPatch(
				Nullable[string]{Set: false},
				Nullable[string]{Set: true, Value: nil},
			),
			wantErr: true,
			wantUser: User{
				ID:       1,
				Version:  1,
				Username: "book_worm07",
				Email:    "lol@mail.com",
			},
		},
		{
			name: "patched email invalid format — error, user unchanged",
			patch: NewUserPatch(
				Nullable[string]{Set: false},
				Nullable[string]{Set: true, Value: new("non-email")},
			),
			wantErr: true,
			wantUser: User{
				ID:       1,
				Version:  1,
				Username: "book_worm07",
				Email:    "lol@mail.com",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			u := baseUser
			gotErr := u.ApplyPatch(tt.patch)
			if tt.wantErr {
				if gotErr == nil {
					t.Fatal("ApplyPatch() succeeded unexpectedly")
				}
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("ApplyPatch() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				if u != baseUser {
					t.Errorf("ApplyPatch() mutated user on error: got %+v, want %+v", u, baseUser)
				}
				return
			}

			if gotErr != nil {
				t.Fatalf("ApplyPatch() failed: %v", gotErr)
			}
			if u != tt.wantUser {
				t.Errorf("ApplyPatch() user = %+v, want %+v", u, tt.wantUser)
			}
		})
	}
}

// ValidateUsername и ValidateEmail проверяют поле независимо от другого:
// поэтому во втором поле нарочно лежит неверное значение.

func TestUser_ValidateUsername(t *testing.T) {
	tests := []struct {
		name     string
		username string
		wantErr  bool
	}{
		{name: "valid", username: "book_worm07", wantErr: false},
		{name: "min length", username: "abc", wantErr: false},
		{name: "max length", username: strings.Repeat("a", 30), wantErr: false},
		{name: "too short", username: "ab", wantErr: true},
		{name: "too long", username: strings.Repeat("a", 31), wantErr: true},
		{name: "cyrillic", username: "читатель", wantErr: true},
		{name: "space", username: "book worm", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			u := User{Username: tt.username, Email: "not-an-email"}

			gotErr := u.ValidateUsername()

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("ValidateUsername() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}
			if gotErr != nil {
				t.Errorf("ValidateUsername() failed: %v", gotErr)
			}
		})
	}
}

func TestUser_ValidateEmail(t *testing.T) {
	tests := []struct {
		name    string
		email   string
		wantErr bool
	}{
		{name: "valid", email: "lol@mail.com", wantErr: false},
		{name: "plus and subdomain", email: "first.last+tag@sub.domain.ru", wantErr: false},
		{name: "no at sign", email: "not-an-email", wantErr: true},
		{name: "no domain zone", email: "a@b", wantErr: true},
		{name: "max length", email: strings.Repeat("a", 245) + "@mail.com", wantErr: false}, // 254 символа
		{name: "too long", email: strings.Repeat("a", 246) + "@mail.com", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			u := User{Username: "x", Email: tt.email}

			gotErr := u.ValidateEmail()

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("ValidateEmail() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}
			if gotErr != nil {
				t.Errorf("ValidateEmail() failed: %v", gotErr)
			}
		})
	}
}
