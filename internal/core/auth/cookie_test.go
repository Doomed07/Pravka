package core_auth_test

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
)

func TestNewSessionCookie(t *testing.T) {
	tests := []struct {
		name   string
		secure bool
	}{
		{name: "secure", secure: true},
		{name: "not secure", secure: false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := core_auth.NewSessionCookie("abc", 2*time.Hour, tt.secure)

			if c.Name != "pravki_session" {
				t.Errorf("Name = %q", c.Name)
			}
			if c.Value != "abc" {
				t.Errorf("Value = %q, want abc", c.Value)
			}
			if c.Path != "/" {
				t.Errorf("Path = %q, want /", c.Path)
			}
			if c.MaxAge != 7200 {
				t.Errorf("MaxAge = %d, want 7200", c.MaxAge)
			}
			if !c.HttpOnly {
				t.Error("HttpOnly = false, want true")
			}
			if c.Secure != tt.secure {
				t.Errorf("Secure = %v, want %v", c.Secure, tt.secure)
			}
			if c.SameSite != http.SameSiteLaxMode {
				t.Errorf("SameSite = %v, want Lax", c.SameSite)
			}
		})
	}
}

func TestClearSessionCookie(t *testing.T) {
	c := core_auth.ClearSessionCookie(true)

	if c.Name != core_auth.SessionCookieName {
		t.Errorf("Name = %q, want %q", c.Name, core_auth.SessionCookieName)
	}
	if c.Value != "" {
		t.Errorf("Value = %q, want empty", c.Value)
	}
	if c.MaxAge >= 0 {
		t.Errorf("MaxAge = %d, want negative", c.MaxAge)
	}
	// удаляется только cookie с теми же Name+Path, поэтому Path обязан совпадать с NewSessionCookie
	if c.Path != core_auth.NewSessionCookie("x", time.Hour, true).Path {
		t.Errorf("Path = %q, differs from NewSessionCookie", c.Path)
	}
	if !c.Secure || !c.HttpOnly {
		t.Errorf("Secure/HttpOnly = %v/%v, want true/true", c.Secure, c.HttpOnly)
	}
}

// Проверяем то, что реально уйдёт браузеру: строку заголовка Set-Cookie.
func TestCookies_SetCookieHeader(t *testing.T) {
	tests := []struct {
		name   string
		cookie *http.Cookie
		want   []string
	}{
		{
			name:   "session cookie",
			cookie: core_auth.NewSessionCookie("abc", 2*time.Hour, true),
			want:   []string{"pravki_session=abc", "Path=/", "Max-Age=7200", "HttpOnly", "Secure", "SameSite=Lax"},
		},
		{
			name:   "clear cookie",
			cookie: core_auth.ClearSessionCookie(false),
			want:   []string{"pravki_session=", "Path=/", "Max-Age=0", "HttpOnly", "SameSite=Lax"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			http.SetCookie(rec, tt.cookie)

			header := rec.Header().Get("Set-Cookie")
			for _, part := range tt.want {
				if !strings.Contains(header, part) {
					t.Errorf("Set-Cookie = %q, missing %q", header, part)
				}
			}
		})
	}
}
