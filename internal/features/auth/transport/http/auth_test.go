package auth_transport_http

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"go.uber.org/zap"
)

const (
	testTTL      = 720 * time.Hour
	testPassword = "LoveBooks01!"
	testToken    = "session-token-value"

	validRegisterBody = `{"username":"book_worm07","email":"lol@mail.com","password":"LoveBooks01!"}`
	validLoginBody    = `{"login":"book_worm07","password":"LoveBooks01!"}`
)

var (
	errBoom  = errors.New("db is down")
	testUser = core_domain.NewUser(7, 1, "book_worm07", "lol@mail.com", time.Time{})
)

// fakeAuthService — подставной сервис: запоминает, с чем его вызвали,
// и возвращает заранее заданный ответ. Настоящий bcrypt и база не нужны.
type fakeAuthService struct {
	user  core_domain.User
	token string
	err   error

	registerCalls, loginCalls, logoutCalls int
	gotUsername, gotEmail, gotPassword     string
	gotLogin, gotLogoutToken               string
}

func (f *fakeAuthService) Register(ctx context.Context, username, email, password string) (core_domain.User, string, error) {
	f.registerCalls++
	f.gotUsername, f.gotEmail, f.gotPassword = username, email, password
	if f.err != nil {
		return core_domain.User{}, "", f.err
	}
	return f.user, f.token, nil
}

func (f *fakeAuthService) Login(ctx context.Context, login, password string) (core_domain.User, string, error) {
	f.loginCalls++
	f.gotLogin, f.gotPassword = login, password
	if f.err != nil {
		return core_domain.User{}, "", f.err
	}
	return f.user, f.token, nil
}

func (f *fakeAuthService) Logout(ctx context.Context, token string) error {
	f.logoutCalls++
	f.gotLogoutToken = token
	return f.err
}

func newFakeService(err error) *fakeAuthService {
	return &fakeAuthService{user: testUser, token: testToken, err: err}
}

func newRequest(method, target, body string) *http.Request {
	r := httptest.NewRequest(method, target, strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	// в проде логгер кладёт в контекст middleware; без него FromCtx паникует
	return r.WithContext(core_logger.ToCtx(r.Context(), &core_logger.Logger{Logger: zap.NewNop()}))
}

func findCookie(rec *httptest.ResponseRecorder, name string) *http.Cookie {
	for _, c := range rec.Result().Cookies() {
		if c.Name == name {
			return c
		}
	}
	return nil
}

// assertSessionCookie проверяет cookie с токеном ровно так, как её увидит браузер.
func assertSessionCookie(t *testing.T, rec *httptest.ResponseRecorder, secure bool) {
	t.Helper()
	c := findCookie(rec, core_auth.SessionCookieName)
	if c == nil {
		t.Fatalf("no %s cookie; Set-Cookie = %q", core_auth.SessionCookieName, rec.Header().Values("Set-Cookie"))
	}
	if c.Value != testToken {
		t.Errorf("cookie value = %q, want %q", c.Value, testToken)
	}
	if c.Path != "/" {
		t.Errorf("cookie Path = %q, want /", c.Path)
	}
	if want := int(testTTL.Seconds()); c.MaxAge != want {
		t.Errorf("cookie MaxAge = %d, want %d", c.MaxAge, want)
	}
	if !c.HttpOnly {
		t.Error("cookie must be HttpOnly: JS must not read the session token")
	}
	if c.SameSite != http.SameSiteLaxMode {
		t.Errorf("cookie SameSite = %v, want Lax", c.SameSite)
	}
	if c.Secure != secure {
		t.Errorf("cookie Secure = %v, want %v", c.Secure, secure)
	}
}

// assertClearedCookie: браузеру велено удалить cookie (пустое значение, MaxAge < 0).
func assertClearedCookie(t *testing.T, rec *httptest.ResponseRecorder, secure bool) {
	t.Helper()
	c := findCookie(rec, core_auth.SessionCookieName)
	if c == nil {
		t.Fatalf("no clearing cookie; Set-Cookie = %q", rec.Header().Values("Set-Cookie"))
	}
	if c.Value != "" || c.MaxAge >= 0 {
		t.Errorf("cookie = %q MaxAge %d, want empty value and negative MaxAge", c.Value, c.MaxAge)
	}
	if c.Path != "/" || !c.HttpOnly || c.Secure != secure {
		t.Errorf("cookie Path/HttpOnly/Secure = %q/%v/%v, want //true/%v", c.Path, c.HttpOnly, c.Secure, secure)
	}
}

func assertNoStore(t *testing.T, rec *httptest.ResponseRecorder) {
	t.Helper()
	if got := rec.Header().Get("Cache-Control"); got != "no-store" {
		t.Errorf("Cache-Control = %q, want no-store", got)
	}
}

// assertUserBody: в теле ровно три поля. Хеша, пароля и версии там быть не должно.
func assertUserBody(t *testing.T, rec *httptest.ResponseRecorder) {
	t.Helper()
	var body map[string]any
	if err := json.NewDecoder(strings.NewReader(rec.Body.String())).Decode(&body); err != nil {
		t.Fatalf("decode response: %v; body = %q", err, rec.Body.String())
	}
	if len(body) != 3 {
		t.Errorf("response fields = %v, want exactly id, username, email", body)
	}
	if body["id"] != float64(7) || body["username"] != "book_worm07" || body["email"] != "lol@mail.com" {
		t.Errorf("response = %v, want id 7, username book_worm07, email lol@mail.com", body)
	}
}

func assertNoSecrets(t *testing.T, rec *httptest.ResponseRecorder) {
	t.Helper()
	body := rec.Body.String()
	for _, secret := range []string{testPassword, testToken, "$2a$", "password_hash"} {
		if strings.Contains(body, secret) {
			t.Errorf("response body leaks %q: %s", secret, body)
		}
	}
}

func TestAuthHTTPHandler_Register(t *testing.T) {
	tests := []struct {
		name       string
		body       string
		svcErr     error
		wantStatus int
		wantCalled bool // дошёл ли запрос до сервиса
	}{
		{name: "ok", body: validRegisterBody, wantStatus: http.StatusCreated, wantCalled: true},
		{name: "invalid JSON", body: `{"username": `, wantStatus: http.StatusBadRequest},
		{name: "empty object", body: `{}`, wantStatus: http.StatusBadRequest},
		{name: "missing username", body: `{"email":"lol@mail.com","password":"LoveBooks01!"}`, wantStatus: http.StatusBadRequest},
		{name: "missing email", body: `{"username":"book_worm07","password":"LoveBooks01!"}`, wantStatus: http.StatusBadRequest},
		{name: "missing password", body: `{"username":"book_worm07","email":"lol@mail.com"}`, wantStatus: http.StatusBadRequest},
		{name: "empty password", body: `{"username":"book_worm07","email":"lol@mail.com","password":""}`, wantStatus: http.StatusBadRequest},
		{name: "password has wrong type", body: `{"username":"book_worm07","email":"lol@mail.com","password":123}`, wantStatus: http.StatusBadRequest},
		{name: "taken username or email", body: validRegisterBody, svcErr: fmt.Errorf("create user: %w", core_errors.ErrConflict), wantStatus: http.StatusConflict, wantCalled: true},
		{name: "rejected by service", body: validRegisterBody, svcErr: fmt.Errorf("validate: %w", core_errors.ErrInvalidArgument), wantStatus: http.StatusBadRequest, wantCalled: true},
		{name: "service failure", body: validRegisterBody, svcErr: errBoom, wantStatus: http.StatusInternalServerError, wantCalled: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			svc := newFakeService(tt.svcErr)
			h := NewAuthHTTPHandler(svc, testTTL, false, "")
			rec := httptest.NewRecorder()

			h.Register(rec, newRequest(http.MethodPost, "/auth/register", tt.body))

			if rec.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d; body = %s", rec.Code, tt.wantStatus, rec.Body.String())
			}
			if called := svc.registerCalls == 1; called != tt.wantCalled {
				t.Errorf("service called = %v, want %v", called, tt.wantCalled)
			}
			if tt.wantStatus != http.StatusCreated {
				if c := findCookie(rec, core_auth.SessionCookieName); c != nil {
					t.Errorf("failed registration must not set a cookie, got %+v", c)
				}
			}
			assertNoSecrets(t, rec)
		})
	}
}

func TestAuthHTTPHandler_Register_Success(t *testing.T) {
	for _, secure := range []bool{false, true} {
		t.Run(fmt.Sprintf("secure=%v", secure), func(t *testing.T) {
			svc := newFakeService(nil)
			h := NewAuthHTTPHandler(svc, testTTL, secure, "")
			rec := httptest.NewRecorder()

			h.Register(rec, newRequest(http.MethodPost, "/auth/register", validRegisterBody))

			if rec.Code != http.StatusCreated {
				t.Fatalf("status = %d, want 201", rec.Code)
			}
			if svc.gotUsername != "book_worm07" || svc.gotEmail != "lol@mail.com" || svc.gotPassword != testPassword {
				t.Errorf("service got %q %q %q, want the request fields untouched",
					svc.gotUsername, svc.gotEmail, svc.gotPassword)
			}
			assertSessionCookie(t, rec, secure)
			assertNoStore(t, rec)
			assertUserBody(t, rec)
			assertNoSecrets(t, rec)
		})
	}
}

func TestAuthHTTPHandler_Login(t *testing.T) {
	tests := []struct {
		name       string
		body       string
		svcErr     error
		wantStatus int
		wantCalled bool
	}{
		{name: "ok", body: validLoginBody, wantStatus: http.StatusOK, wantCalled: true},
		{name: "login by email", body: `{"login":"lol@mail.com","password":"LoveBooks01!"}`, wantStatus: http.StatusOK, wantCalled: true},
		{name: "invalid JSON", body: `{"login": `, wantStatus: http.StatusBadRequest},
		{name: "empty object", body: `{}`, wantStatus: http.StatusBadRequest},
		{name: "missing login", body: `{"password":"LoveBooks01!"}`, wantStatus: http.StatusBadRequest},
		{name: "missing password", body: `{"login":"book_worm07"}`, wantStatus: http.StatusBadRequest},
		{name: "wrong credentials", body: validLoginBody, svcErr: fmt.Errorf("invalid login or password: %w", core_errors.ErrUnauthorized), wantStatus: http.StatusUnauthorized, wantCalled: true},
		{name: "service failure", body: validLoginBody, svcErr: errBoom, wantStatus: http.StatusInternalServerError, wantCalled: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			svc := newFakeService(tt.svcErr)
			h := NewAuthHTTPHandler(svc, testTTL, false, "")
			rec := httptest.NewRecorder()

			h.Login(rec, newRequest(http.MethodPost, "/auth/login", tt.body))

			if rec.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d; body = %s", rec.Code, tt.wantStatus, rec.Body.String())
			}
			if called := svc.loginCalls == 1; called != tt.wantCalled {
				t.Errorf("service called = %v, want %v", called, tt.wantCalled)
			}
			if tt.wantStatus == http.StatusOK {
				assertSessionCookie(t, rec, false)
				assertNoStore(t, rec)
				assertUserBody(t, rec)
			} else if c := findCookie(rec, core_auth.SessionCookieName); c != nil {
				t.Errorf("failed login must not set a cookie, got %+v", c)
			}
			assertNoSecrets(t, rec)
		})
	}
}

func TestAuthHTTPHandler_Login_PassesFieldsToService(t *testing.T) {
	svc := newFakeService(nil)
	h := NewAuthHTTPHandler(svc, testTTL, true, "")
	rec := httptest.NewRecorder()

	h.Login(rec, newRequest(http.MethodPost, "/auth/login", `{"login":"lol@mail.com","password":"LoveBooks01!"}`))

	if svc.gotLogin != "lol@mail.com" || svc.gotPassword != testPassword {
		t.Errorf("service got login %q password %q, want the request fields untouched", svc.gotLogin, svc.gotPassword)
	}
	assertSessionCookie(t, rec, true)
}

func TestAuthHTTPHandler_Logout(t *testing.T) {
	withCookie := func() *http.Request {
		r := newRequest(http.MethodPost, "/auth/logout", "")
		r.AddCookie(&http.Cookie{Name: core_auth.SessionCookieName, Value: testToken})
		return r
	}

	tests := []struct {
		name       string
		request    func() *http.Request
		svcErr     error
		wantStatus int
		wantToken  string // токен, с которым должен быть вызван сервис; "" — вызова быть не должно
	}{
		{name: "with session", request: withCookie, wantStatus: http.StatusNoContent, wantToken: testToken},
		{name: "without cookie", request: func() *http.Request { return newRequest(http.MethodPost, "/auth/logout", "") }, wantStatus: http.StatusNoContent},
		{name: "service failure", request: withCookie, svcErr: errBoom, wantStatus: http.StatusInternalServerError, wantToken: testToken},
	}
	for _, tt := range tests {
		for _, secure := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s secure=%v", tt.name, secure), func(t *testing.T) {
				svc := newFakeService(tt.svcErr)
				h := NewAuthHTTPHandler(svc, testTTL, secure, "")
				rec := httptest.NewRecorder()

				h.Logout(rec, tt.request())

				if rec.Code != tt.wantStatus {
					t.Fatalf("status = %d, want %d", rec.Code, tt.wantStatus)
				}
				if tt.wantToken == "" && svc.logoutCalls != 0 {
					t.Errorf("service must not be called without a cookie, calls = %d", svc.logoutCalls)
				}
				if tt.wantToken != "" && (svc.logoutCalls != 1 || svc.gotLogoutToken != tt.wantToken) {
					t.Errorf("service calls = %d token %q, want 1 call with %q", svc.logoutCalls, svc.gotLogoutToken, tt.wantToken)
				}
				// браузеру велено удалить cookie в любом случае, даже если сервер упал
				assertClearedCookie(t, rec, secure)
				assertNoStore(t, rec)
				if tt.wantStatus == http.StatusNoContent && rec.Body.Len() != 0 {
					t.Errorf("204 must have an empty body, got %q", rec.Body.String())
				}
			})
		}
	}
}

func TestAuthHTTPHandler_Me(t *testing.T) {
	identity := core_auth.Identity{UserID: 7, Username: "book_worm07", Email: "lol@mail.com"}

	t.Run("logged in", func(t *testing.T) {
		h := NewAuthHTTPHandler(newFakeService(nil), testTTL, false, "")
		r := newRequest(http.MethodGet, "/auth/me", "")
		r = r.WithContext(core_auth.WithIdentity(r.Context(), identity))
		rec := httptest.NewRecorder()

		h.Me(rec, r)

		if rec.Code != http.StatusOK {
			t.Fatalf("status = %d, want 200", rec.Code)
		}
		assertNoStore(t, rec)
		assertUserBody(t, rec)
		if c := findCookie(rec, core_auth.SessionCookieName); c != nil {
			t.Errorf("/auth/me must not touch the session cookie, got %+v", c)
		}
	})

	t.Run("anonymous", func(t *testing.T) {
		h := NewAuthHTTPHandler(newFakeService(nil), testTTL, false, "")
		rec := httptest.NewRecorder()

		h.Me(rec, newRequest(http.MethodGet, "/auth/me", ""))

		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("status = %d, want 401", rec.Code)
		}
		if strings.Contains(rec.Body.String(), "lol@mail.com") {
			t.Errorf("401 response must not contain user data: %s", rec.Body.String())
		}
	})
}

func TestAuthHTTPHandler_Routes(t *testing.T) {
	h := NewAuthHTTPHandler(newFakeService(nil), testTTL, false, "")
	want := map[string]bool{
		"POST /auth/register": true,
		"POST /auth/login":    true,
		"POST /auth/logout":   true,
		"GET /auth/me":        true,
	}

	for _, route := range h.Routes() {
		key := route.Method + " " + route.Path
		if !want[key] {
			t.Errorf("unexpected route %q", key)
		}
		if route.Handler == nil {
			t.Errorf("route %q has no handler", key)
		}
		delete(want, key)
	}
	for key := range want {
		t.Errorf("missing route %q", key)
	}
}

// На удалённом сервере регистрация закрыта кодом приглашения (AUTH_SIGNUP_CODE).
func TestAuthHTTPHandler_RegisterInviteCode(t *testing.T) {
	tests := []struct {
		name       string
		body       string
		wantStatus int
		wantCalled bool
	}{
		{name: "no code", body: validRegisterBody, wantStatus: http.StatusForbidden},
		{name: "wrong code", body: `{"username":"book_worm07","email":"lol@mail.com","password":"LoveBooks01!","invite_code":"nope"}`, wantStatus: http.StatusForbidden},
		{name: "right code", body: `{"username":"book_worm07","email":"lol@mail.com","password":"LoveBooks01!","invite_code":"s3cret"}`, wantStatus: http.StatusCreated, wantCalled: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			svc := newFakeService(nil)
			h := NewAuthHTTPHandler(svc, testTTL, false, "s3cret")
			rec := httptest.NewRecorder()
			h.Register(rec, newRequest(http.MethodPost, "/auth/register", tt.body))
			if rec.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d; body = %s", rec.Code, tt.wantStatus, rec.Body.String())
			}
			if called := svc.registerCalls == 1; called != tt.wantCalled {
				t.Errorf("service called = %v, want %v", called, tt.wantCalled)
			}
		})
	}
}
