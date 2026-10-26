package auth_service

import (
	"context"
	"errors"
	"strings"
	"testing"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
	"github.com/prometheus/client_golang/prometheus/testutil"
)

// Счётчики глобальные: сравниваем прирост за время одного вызова, а не абсолютное значение.
type authCounters struct{ registrations, loginOK, loginInvalid float64 }

func readAuthCounters() authCounters {
	return authCounters{
		registrations: testutil.ToFloat64(core_metrics.Registrations),
		loginOK:       testutil.ToFloat64(core_metrics.Logins.WithLabelValues(core_metrics.LoginSuccess)),
		loginInvalid:  testutil.ToFloat64(core_metrics.Logins.WithLabelValues(core_metrics.LoginInvalid)),
	}
}

func (c authCounters) since(before authCounters) authCounters {
	return authCounters{
		registrations: c.registrations - before.registrations,
		loginOK:       c.loginOK - before.loginOK,
		loginInvalid:  c.loginInvalid - before.loginInvalid,
	}
}

func TestAuthService_Register_Metrics(t *testing.T) {
	tests := []struct {
		name    string
		prepare func(*fakeAuthRepository, *testing.T)
		user    string
		email   string
		pass    string
		want    float64 // на сколько вырос счётчик регистраций
	}{
		{name: "success", user: "kant", email: "user@example.ru", pass: "Passw0rd!", want: 1},
		{name: "invalid input", user: "ab", email: "user@example.ru", pass: "Passw0rd!", want: 0},
		{
			name: "username already taken",
			prepare: func(r *fakeAuthRepository, t *testing.T) {
				r.seedUser(t, 1, "kant", "other@mail.ru", "Passw0rd!")
			},
			user: "kant", email: "user@example.ru", pass: "Passw0rd!", want: 0,
		},
		{
			name:    "session could not be created",
			prepare: func(r *fakeAuthRepository, t *testing.T) { r.createSessionErr = errBoom },
			user:    "kant", email: "user@example.ru", pass: "Passw0rd!", want: 0,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			repo := newFakeRepo()
			if tt.prepare != nil {
				tt.prepare(repo, t)
			}
			s := newTestService(t, repo)
			before := readAuthCounters()

			_, _, _ = s.Register(context.Background(), tt.user, tt.email, tt.pass)

			got := readAuthCounters().since(before)
			if got.registrations != tt.want {
				t.Errorf("registrations grew by %v, want %v", got.registrations, tt.want)
			}
			if got.loginOK != 0 || got.loginInvalid != 0 {
				t.Errorf("Register touched login counters: %+v", got)
			}
		})
	}
}

func TestAuthService_Login_Metrics(t *testing.T) {
	tests := []struct {
		name         string
		login        string
		password     string
		repoErr      error
		wantOK       float64
		wantInvalid  float64
		wantLoginErr error
	}{
		{name: "by username", login: "kant", password: "Passw0rd!", wantOK: 1},
		{name: "by email", login: "user@example.ru", password: "Passw0rd!", wantOK: 1},
		{name: "wrong password", login: "kant", password: "Wrong0rd!", wantInvalid: 1, wantLoginErr: core_errors.ErrUnauthorized},
		{name: "unknown user", login: "nobody", password: "Passw0rd!", wantInvalid: 1, wantLoginErr: core_errors.ErrUnauthorized},
		{
			name: "oversized password", login: "kant", password: strings.Repeat("a", core_domain.MaxPasswordLen+1),
			wantInvalid: 1, wantLoginErr: core_errors.ErrUnauthorized,
		},
		// сбой базы — не ошибка пользователя: ни «успех», ни «неверный пароль»
		{name: "database failure is not counted", login: "kant", password: "Passw0rd!", repoErr: errBoom, wantLoginErr: errBoom},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			repo := newFakeRepo()
			repo.seedUser(t, 1, "kant", "user@example.ru", "Passw0rd!")
			repo.credsErr = tt.repoErr
			s := newTestService(t, repo)
			before := readAuthCounters()

			_, _, err := s.Login(context.Background(), tt.login, tt.password)

			if tt.wantLoginErr == nil && err != nil {
				t.Fatalf("Login() failed: %v", err)
			}
			if tt.wantLoginErr != nil && !errors.Is(err, tt.wantLoginErr) {
				t.Fatalf("Login() error = %v, want %v", err, tt.wantLoginErr)
			}
			got := readAuthCounters().since(before)
			if got.loginOK != tt.wantOK || got.loginInvalid != tt.wantInvalid {
				t.Errorf("login counters grew by ok=%v invalid=%v, want ok=%v invalid=%v",
					got.loginOK, got.loginInvalid, tt.wantOK, tt.wantInvalid)
			}
			if got.registrations != 0 {
				t.Errorf("Login touched the registrations counter: %v", got.registrations)
			}
		})
	}
}
