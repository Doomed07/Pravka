package core_http_middleware

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"go.uber.org/zap"
)

var errBoom = errors.New("db is down")

// spy — «следующий обработчик»: запоминает, дошёл ли до него запрос и что лежало в контексте.
type spy struct {
	called      bool
	identity    core_auth.Identity
	hasIdentity bool
}

func (s *spy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.called = true
	s.identity, s.hasIdentity = core_auth.IdentityFromCtx(r.Context())
	w.WriteHeader(http.StatusOK)
}

// fakeAuthenticator — подставной сервис: запоминает токен и возвращает заданный ответ.
type fakeAuthenticator struct {
	user     core_domain.User
	err      error
	calls    int
	gotToken string
}

func (f *fakeAuthenticator) Authenticate(ctx context.Context, token string) (core_domain.User, error) {
	f.calls++
	f.gotToken = token
	if f.err != nil {
		return core_domain.User{}, f.err
	}
	return f.user, nil
}

// newRequest кладёт в контекст логгер: в проде это делает глобальный middleware Logger,
// а без него core_logger.FromCtx паникует.
func newRequest(method, target string) *http.Request {
	r := httptest.NewRequest(method, target, nil)
	return r.WithContext(core_logger.ToCtx(r.Context(), &core_logger.Logger{Logger: zap.NewNop()}))
}

func withIdentity(r *http.Request, identity core_auth.Identity) *http.Request {
	return r.WithContext(core_auth.WithIdentity(r.Context(), identity))
}

func sessionCookie(value string) *http.Cookie {
	return &http.Cookie{Name: core_auth.SessionCookieName, Value: value}
}

var testUser = core_domain.NewUser(7, 1, "book_worm07", "lol@mail.com", time.Date(2026, 10, 8, 12, 0, 0, 0, time.UTC))

func TestAuthenticate(t *testing.T) {
	tests := []struct {
		name         string
		cookie       *http.Cookie
		authErr      error
		wantCalls    int
		wantStatus   int
		wantNext     bool // дошёл ли запрос до следующего обработчика
		wantIdentity bool
	}{
		{name: "no cookie is a guest", wantStatus: http.StatusOK, wantNext: true},
		{name: "empty cookie is a guest", cookie: sessionCookie(""), wantStatus: http.StatusOK, wantNext: true},
		{name: "other cookie is ignored", cookie: &http.Cookie{Name: "other", Value: "x"}, wantStatus: http.StatusOK, wantNext: true},
		{name: "valid session", cookie: sessionCookie("token-1"), wantCalls: 1, wantStatus: http.StatusOK, wantNext: true, wantIdentity: true},
		{name: "unknown or expired session is a guest", cookie: sessionCookie("token-1"), authErr: fmt.Errorf("session expired: %w", core_errors.ErrUnauthorized),
			wantCalls: 1, wantStatus: http.StatusOK, wantNext: true},
		{name: "database failure stops the request", cookie: sessionCookie("token-1"), authErr: errBoom,
			wantCalls: 1, wantStatus: http.StatusInternalServerError},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			auth := &fakeAuthenticator{user: testUser, err: tt.authErr}
			next := &spy{}
			r := newRequest(http.MethodGet, "/api/v1/users")
			if tt.cookie != nil {
				r.AddCookie(tt.cookie)
			}
			rec := httptest.NewRecorder()

			Authenticate(auth)(next).ServeHTTP(rec, r)

			if rec.Code != tt.wantStatus {
				t.Errorf("status = %d, want %d", rec.Code, tt.wantStatus)
			}
			if auth.calls != tt.wantCalls {
				t.Errorf("Authenticate calls = %d, want %d", auth.calls, tt.wantCalls)
			}
			if next.called != tt.wantNext {
				t.Errorf("next called = %v, want %v", next.called, tt.wantNext)
			}
			if next.hasIdentity != tt.wantIdentity {
				t.Errorf("identity in context = %v, want %v", next.hasIdentity, tt.wantIdentity)
			}
			if tt.wantIdentity {
				want := core_auth.Identity{UserID: 7, Username: "book_worm07", Email: "lol@mail.com"}
				if next.identity != want {
					t.Errorf("identity = %+v, want %+v", next.identity, want)
				}
				if auth.gotToken != "token-1" {
					t.Errorf("service got token %q, want the cookie value token-1", auth.gotToken)
				}
			}
		})
	}
}

func TestRequireAuth(t *testing.T) {
	tests := []struct {
		name       string
		identity   *core_auth.Identity
		wantStatus int
	}{
		{name: "guest", wantStatus: http.StatusUnauthorized},
		{name: "logged in", identity: &core_auth.Identity{UserID: 7, Username: "book_worm07"}, wantStatus: http.StatusOK},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			next := &spy{}
			r := newRequest(http.MethodGet, "/api/v1/anything")
			if tt.identity != nil {
				r = withIdentity(r, *tt.identity)
			}
			rec := httptest.NewRecorder()

			RequireAuth()(next).ServeHTTP(rec, r)

			if rec.Code != tt.wantStatus {
				t.Errorf("status = %d, want %d", rec.Code, tt.wantStatus)
			}
			if next.called != (tt.wantStatus == http.StatusOK) {
				t.Errorf("next called = %v with status %d", next.called, rec.Code)
			}
		})
	}
}

// RequireSelf проверяем через настоящий ServeMux: так видно, что r.PathValue
// доступен внутри middleware (он оборачивает обработчик ПОСЛЕ сопоставления шаблона).
func TestRequireSelf(t *testing.T) {
	me := &core_auth.Identity{UserID: 7, Username: "book_worm07"}

	tests := []struct {
		name       string
		param      string // имя параметра в RequireSelf; шаблон маршрута всегда {id}
		identity   *core_auth.Identity
		target     string
		wantStatus int
	}{
		{name: "guest", param: "id", target: "/users/7", wantStatus: http.StatusUnauthorized},
		// гость с мусорным id всё равно получает 401: по ответу нельзя отличить «адрес верный» от «неверный»
		{name: "guest with garbage id", param: "id", target: "/users/abc", wantStatus: http.StatusUnauthorized},
		{name: "own profile", param: "id", identity: me, target: "/users/7", wantStatus: http.StatusOK},
		{name: "someone else's profile", param: "id", identity: me, target: "/users/8", wantStatus: http.StatusForbidden},
		{name: "id is not a number", param: "id", identity: me, target: "/users/abc", wantStatus: http.StatusBadRequest},
		{name: "id is too big for int", param: "id", identity: me, target: "/users/99999999999999999999", wantStatus: http.StatusBadRequest},
		{name: "negative id", param: "id", identity: me, target: "/users/-7", wantStatus: http.StatusForbidden},
		// опечатка в имени параметра не должна открывать доступ
		{name: "wrong param name never grants access", param: "user_id", identity: me, target: "/users/7", wantStatus: http.StatusBadRequest},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			next := &spy{}
			mux := http.NewServeMux()
			mux.Handle("PATCH /users/{id}", RequireSelf(tt.param)(next))

			r := newRequest(http.MethodPatch, tt.target)
			if tt.identity != nil {
				r = withIdentity(r, *tt.identity)
			}
			rec := httptest.NewRecorder()

			mux.ServeHTTP(rec, r)

			if rec.Code != tt.wantStatus {
				t.Errorf("status = %d, want %d; body = %s", rec.Code, tt.wantStatus, rec.Body.String())
			}
			if next.called != (tt.wantStatus == http.StatusOK) {
				t.Errorf("next called = %v with status %d", next.called, rec.Code)
			}
		})
	}
}

// Authenticate + RequireSelf вместе, как на роутере: от cookie до решения «можно ли».
func TestAuthenticateThenRequireSelf(t *testing.T) {
	tests := []struct {
		name       string
		cookie     *http.Cookie
		authErr    error
		target     string
		wantStatus int
	}{
		{name: "own profile with valid session", cookie: sessionCookie("t"), target: "/users/7", wantStatus: http.StatusOK},
		{name: "someone else's profile", cookie: sessionCookie("t"), target: "/users/8", wantStatus: http.StatusForbidden},
		{name: "no cookie", target: "/users/7", wantStatus: http.StatusUnauthorized},
		{name: "expired session", cookie: sessionCookie("t"), authErr: core_errors.ErrUnauthorized, target: "/users/7", wantStatus: http.StatusUnauthorized},
		{name: "database failure", cookie: sessionCookie("t"), authErr: errBoom, target: "/users/7", wantStatus: http.StatusInternalServerError},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			auth := &fakeAuthenticator{user: testUser, err: tt.authErr}
			next := &spy{}
			mux := http.NewServeMux()
			mux.Handle("PATCH /users/{id}", RequireSelf("id")(next))
			handler := Authenticate(auth)(mux)

			r := newRequest(http.MethodPatch, tt.target)
			if tt.cookie != nil {
				r.AddCookie(tt.cookie)
			}
			rec := httptest.NewRecorder()

			handler.ServeHTTP(rec, r)

			if rec.Code != tt.wantStatus {
				t.Errorf("status = %d, want %d", rec.Code, tt.wantStatus)
			}
			if next.called != (tt.wantStatus == http.StatusOK) {
				t.Errorf("next called = %v with status %d", next.called, rec.Code)
			}
		})
	}
}
