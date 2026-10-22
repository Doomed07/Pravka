package core_http_server

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"testing/fstest"

	core_http_middleware "github.com/Doomed07/Pravka/internal/core/transport/http/middleware"
)

// writeBody — обработчик, который просто пишет строку: по ней видно, какой маршрут сработал.
func writeBody(body string) http.HandlerFunc {
	return func(rw http.ResponseWriter, r *http.Request) {
		_, _ = rw.Write([]byte(body))
	}
}

func TestHTTPServer_RegisterRoutes(t *testing.T) {
	// middleware помечает ответ заголовком — так проверяем, что Handler() их применяет
	mark := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
			rw.Header().Set("X-Test-Middleware", "on")
			next.ServeHTTP(rw, r)
		})
	}

	srv := NewHTTPServer(Config{}, nil, core_http_middleware.Middleware(mark))

	api := NewAPIVersionRouter(ApiVersion1)
	api.RegisterRoutes(Route{Method: http.MethodGet, Path: "/ping", Handler: writeBody("api")})
	srv.RegisterAPIRouters(api)

	// если шаблоны конфликтуют, ServeMux паникует прямо здесь, при регистрации
	srv.RegisterRoutes(
		Route{Method: http.MethodGet, Path: "/{$}", Handler: writeBody("home")},
		Route{Method: http.MethodGet, Path: "/books/{id}", Handler: writeBody("book")},
		Route{Path: "/", Handler: writeBody("not found page")},
	)

	tests := []struct {
		name   string
		method string
		path   string
		want   string
	}{
		{name: "home", method: http.MethodGet, path: "/", want: "home"},
		{name: "page with path value", method: http.MethodGet, path: "/books/3", want: "book"},
		{name: "api is not shadowed by the catch-all", method: http.MethodGet, path: "/api/v1/ping", want: "api"},
		{name: "unknown path goes to the catch-all", method: http.MethodGet, path: "/nope", want: "not found page"},
		{name: "route without method matches any method", method: http.MethodPost, path: "/", want: "not found page"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			srv.Handler().ServeHTTP(rec, httptest.NewRequest(tt.method, tt.path, nil))

			if got := rec.Body.String(); got != tt.want {
				t.Errorf("body = %q, want %q", got, tt.want)
			}
			if rec.Header().Get("X-Test-Middleware") != "on" {
				t.Error("middleware was not applied")
			}
		})
	}
}

func TestHTTPServer_RegisterStatic(t *testing.T) {
	// fstest.MapFS — файловая система в памяти: настоящие файлы на диске не нужны
	files := fstest.MapFS{
		"css/main.css": {Data: []byte("body{}")},
		"img/logo.svg": {Data: []byte("<svg/>")},
	}

	srv := NewHTTPServer(Config{}, nil)
	srv.RegisterStatic("/static/", files)

	tests := []struct {
		name            string
		path            string
		wantStatus      int
		wantContentType string
	}{
		{name: "css file", path: "/static/css/main.css", wantStatus: http.StatusOK, wantContentType: "text/css; charset=utf-8"},
		{name: "svg file", path: "/static/img/logo.svg", wantStatus: http.StatusOK, wantContentType: "image/svg+xml"},
		{name: "root directory is hidden", path: "/static/", wantStatus: http.StatusNotFound},
		{name: "nested directory is hidden", path: "/static/css/", wantStatus: http.StatusNotFound},
		{name: "missing file", path: "/static/css/nope.css", wantStatus: http.StatusNotFound},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			srv.Handler().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, tt.path, nil))

			if rec.Code != tt.wantStatus {
				t.Errorf("status = %d, want %d", rec.Code, tt.wantStatus)
			}
			if tt.wantContentType != "" && rec.Header().Get("Content-Type") != tt.wantContentType {
				t.Errorf("Content-Type = %q, want %q", rec.Header().Get("Content-Type"), tt.wantContentType)
			}
		})
	}
}
