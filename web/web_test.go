package web

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	core_http_server "github.com/Doomed07/Pravka/internal/core/transport/http/server"
)

func TestRoutes(t *testing.T) {
	srv := core_http_server.NewHTTPServer(core_http_server.Config{}, nil)
	srv.RegisterStatic("/static/", Static())
	srv.RegisterRoutes(Routes()...)

	tests := []struct {
		name, method, path string
		wantStatus         int
		wantContentType    string
		wantScript         string // какой модуль страницы подключён — по нему видно, что отдан нужный файл
	}{
		{"home", http.MethodGet, "/", http.StatusOK, "text/html; charset=utf-8", "pages/home.js"},
		{"review", http.MethodGet, "/reviews/12", http.StatusOK, "text/html; charset=utf-8", "pages/review.js"},
		{"signup", http.MethodGet, "/signup", http.StatusOK, "text/html; charset=utf-8", "pages/signup.js"},
		{"login", http.MethodGet, "/login?next=/reviews/3", http.StatusOK, "text/html; charset=utf-8", "pages/login.js"},
		{"about", http.MethodGet, "/about", http.StatusOK, "text/html; charset=utf-8", "pages/static.js"},
		{"unknown page", http.MethodGet, "/nope", http.StatusNotFound, "text/html; charset=utf-8", "pages/static.js"},
		{"unknown api path", http.MethodGet, "/api/v2/x", http.StatusNotFound, "text/plain; charset=utf-8", ""},
		{"script", http.MethodGet, "/static/js/pages/review.js", http.StatusOK, "text/javascript; charset=utf-8", ""},
		{"stylesheet", http.MethodGet, "/static/css/main.css", http.StatusOK, "text/css; charset=utf-8", ""},
		{"no directory listing", http.MethodGet, "/static/js/", http.StatusNotFound, "", ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			srv.Handler().ServeHTTP(rec, httptest.NewRequest(tt.method, tt.path, nil))
			if rec.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d", rec.Code, tt.wantStatus)
			}
			if tt.wantContentType != "" && rec.Header().Get("Content-Type") != tt.wantContentType {
				t.Errorf("content type = %q, want %q", rec.Header().Get("Content-Type"), tt.wantContentType)
			}
			if tt.wantScript != "" && !strings.Contains(rec.Body.String(), tt.wantScript) {
				t.Errorf("page does not include %s", tt.wantScript)
			}
		})
	}
}

// Каждая страница несёт пометку о черновике: продукт не выдаёт окончательных формулировок.
func TestPagesCarryDisclaimer(t *testing.T) {
	for _, name := range []string{"index.html", "review.html", "about.html"} {
		body, err := files.ReadFile("static/" + name)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(string(body), "Черновик — требует вашей проверки") {
			t.Errorf("%s: нет пометки о черновике", name)
		}
	}
}
