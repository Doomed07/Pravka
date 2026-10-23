package core_http_server

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"testing/fstest"

	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
	core_http_middleware "github.com/Doomed07/Pravka/internal/core/transport/http/middleware"
	"github.com/prometheus/client_golang/prometheus/testutil"
)

func requestsTotal(method, route string, status int) float64 {
	return testutil.ToFloat64(core_metrics.HTTPRequestsTotal.WithLabelValues(method, route, strconv.Itoa(status)))
}

// Проверяем сквозь настоящую регистрацию: какой шаблон попадает в метку route
// для API, страниц, запасного обработчика, статики.
func TestHTTPServer_RouteLabels(t *testing.T) {
	srv := NewHTTPServer(Config{}, nil, core_http_middleware.Metrics())

	api := NewAPIVersionRouter(ApiVersion1)
	api.RegisterRoutes(Route{Method: http.MethodGet, Path: "/books/{id}", Handler: writeBody("api")})
	srv.RegisterAPIRouters(api)

	srv.RegisterRoutes(
		Route{Method: http.MethodGet, Path: "/{$}", Handler: writeBody("home")},
		Route{Method: http.MethodGet, Path: "/books/{id}", Handler: writeBody("book")},
		Route{Path: "/", Handler: writeBody("not found page")},
	)
	srv.RegisterStatic("/static/", fstest.MapFS{"css/a.css": {Data: []byte("a{}")}})

	tests := []struct {
		name       string
		target     string
		wantRoute  string
		wantStatus int
	}{
		{name: "api route", target: "/api/v1/books/5", wantRoute: "/api/v1/books/{id}", wantStatus: http.StatusOK},
		{name: "page route", target: "/books/5", wantRoute: "/books/{id}", wantStatus: http.StatusOK},
		{name: "home", target: "/", wantRoute: "/{$}", wantStatus: http.StatusOK},
		{name: "catch-all keeps the raw path out of the label", target: "/some/junk/path", wantRoute: "/", wantStatus: http.StatusOK},
		{name: "static files share one series", target: "/static/css/a.css", wantRoute: "/static/", wantStatus: http.StatusOK},
		// в /api/v1/ нет такого маршрута: до метки дело не дошло
		{name: "unknown api path is unmatched", target: "/api/v1/nope", wantRoute: "unmatched", wantStatus: http.StatusNotFound},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			before := requestsTotal(http.MethodGet, tt.wantRoute, tt.wantStatus)

			rec := httptest.NewRecorder()
			srv.Handler().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, tt.target, nil))

			if rec.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d", rec.Code, tt.wantStatus)
			}
			if got := requestsTotal(http.MethodGet, tt.wantRoute, tt.wantStatus) - before; got != 1 {
				t.Errorf("series {route=%q, status=%d} grew by %v, want 1", tt.wantRoute, tt.wantStatus, got)
			}
		})
	}
}

// Отказы RequireAuth/RequireSelf тоже считаются на своём маршруте, а не как unmatched:
// метка стоит снаружи middleware маршрута.
func TestHTTPServer_RouteLabelCoversRouteMiddleware(t *testing.T) {
	deny := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusUnauthorized)
		})
	}
	srv := NewHTTPServer(Config{}, nil, core_http_middleware.Metrics())
	api := NewAPIVersionRouter(ApiVersion1)
	api.RegisterRoutes(Route{
		Method:      http.MethodGet,
		Path:        "/t/private",
		Handler:     writeBody("secret"),
		Middlewares: []core_http_middleware.Middleware{deny},
	})
	srv.RegisterAPIRouters(api)

	before := requestsTotal(http.MethodGet, "/api/v1/t/private", http.StatusUnauthorized)
	srv.Handler().ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/api/v1/t/private", nil))

	if got := requestsTotal(http.MethodGet, "/api/v1/t/private", http.StatusUnauthorized) - before; got != 1 {
		t.Errorf("401 from route middleware grew its series by %v, want 1", got)
	}
}

func TestMetricsEndpoint(t *testing.T) {
	// ряд появляется в выдаче только после первого запроса
	core_metrics.HTTPRequestsTotal.WithLabelValues(http.MethodGet, "/t/probe", "200").Inc()

	srv := NewHTTPServer(Config{}, nil)
	srv.RegisterRoutes(Route{Method: http.MethodGet, Path: "/metrics", Handler: core_metrics.Handler().ServeHTTP})

	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/metrics", nil))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "text/plain") {
		t.Errorf("Content-Type = %q, want text/plain…", ct)
	}
	body := rec.Body.String()
	for _, want := range []string{
		`pravki_http_requests_total{method="GET",route="/t/probe",status="200"}`,
		"go_goroutines",
		"pravki_registrations_total",
	} {
		if !strings.Contains(body, want) {
			t.Errorf("/metrics output has no %q", want)
		}
	}
}
