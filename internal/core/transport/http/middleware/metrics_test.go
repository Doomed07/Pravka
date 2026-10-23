package core_http_middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
	"github.com/prometheus/client_golang/prometheus/testutil"
)

// Счётчики глобальные и растут от теста к тесту, поэтому везде сравниваем не значение,
// а прирост: «было — стало».
func requestsTotal(method, route string, status int) float64 {
	return testutil.ToFloat64(core_metrics.HTTPRequestsTotal.WithLabelValues(method, route, strconv.Itoa(status)))
}

// durationSamples — сколько раз гистограмма времени ответа записала запрос с такими метками.
func durationSamples(t *testing.T, method, route string) uint64 {
	t.Helper()
	families, err := core_metrics.Registry.Gather()
	if err != nil {
		t.Fatal(err)
	}
	for _, family := range families {
		if family.GetName() != "pravki_http_request_duration_seconds" {
			continue
		}
		for _, m := range family.GetMetric() {
			labels := map[string]string{}
			for _, l := range m.GetLabel() {
				labels[l.GetName()] = l.GetValue()
			}
			if labels["method"] == method && labels["route"] == route {
				return m.GetHistogram().GetSampleCount()
			}
		}
	}
	return 0
}

// hasRouteLabel — есть ли в метриках запросов ряд с таким значением route.
func hasRouteLabel(t *testing.T, route string) bool {
	t.Helper()
	families, err := core_metrics.Registry.Gather()
	if err != nil {
		t.Fatal(err)
	}
	for _, family := range families {
		if family.GetName() != "pravki_http_requests_total" {
			continue
		}
		for _, m := range family.GetMetric() {
			for _, l := range m.GetLabel() {
				if l.GetName() == "route" && l.GetValue() == route {
					return true
				}
			}
		}
	}
	return false
}

func respondWith(status int) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
	})
}

// copyContext делает то же, что Authenticate: отдаёт дальше копию запроса (r.WithContext).
func copyContext(next http.Handler) http.Handler {
	type key struct{}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), key{}, "x")))
	})
}

func TestMetrics_CountsRequest(t *testing.T) {
	tests := []struct {
		name       string
		method     string
		target     string
		handler    http.Handler
		wantMethod string
		wantRoute  string
		wantStatus int
	}{
		{
			name: "status 200 when the handler never calls WriteHeader", method: http.MethodGet, target: "/books/1",
			handler:    RouteLabel("/t/200")(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("ok")) })),
			wantMethod: http.MethodGet, wantRoute: "/t/200", wantStatus: http.StatusOK,
		},
		{
			name: "explicit 201", method: http.MethodPost, target: "/x",
			handler:    RouteLabel("/t/201")(respondWith(http.StatusCreated)),
			wantMethod: http.MethodPost, wantRoute: "/t/201", wantStatus: http.StatusCreated,
		},
		{
			name: "server error", method: http.MethodGet, target: "/x",
			handler:    RouteLabel("/t/500")(respondWith(http.StatusInternalServerError)),
			wantMethod: http.MethodGet, wantRoute: "/t/500", wantStatus: http.StatusInternalServerError,
		},
		{
			name: "no route label means unmatched", method: http.MethodGet, target: "/whatever",
			handler:    respondWith(http.StatusNotFound),
			wantMethod: http.MethodGet, wantRoute: unmatchedRoute, wantStatus: http.StatusNotFound,
		},
		{
			// StripPrefix и Authenticate отдают дальше копии запроса; метка должна дойти до Metrics
			name: "label survives StripPrefix and r.WithContext", method: http.MethodGet, target: "/api/v1/t/{id}",
			handler:    http.StripPrefix("/api/v1", copyContext(RouteLabel("/api/v1/t/copy")(respondWith(http.StatusOK)))),
			wantMethod: http.MethodGet, wantRoute: "/api/v1/t/copy", wantStatus: http.StatusOK,
		},
		{
			name: "unknown method is grouped as OTHER", method: "FOO", target: "/x",
			handler:    RouteLabel("/t/other")(respondWith(http.StatusOK)),
			wantMethod: "OTHER", wantRoute: "/t/other", wantStatus: http.StatusOK,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			before := requestsTotal(tt.wantMethod, tt.wantRoute, tt.wantStatus)
			samplesBefore := durationSamples(t, tt.wantMethod, tt.wantRoute)

			rec := httptest.NewRecorder()
			Metrics()(tt.handler).ServeHTTP(rec, httptest.NewRequest(tt.method, tt.target, nil))

			if got := requestsTotal(tt.wantMethod, tt.wantRoute, tt.wantStatus) - before; got != 1 {
				t.Errorf("requests counter grew by %v, want 1", got)
			}
			if got := durationSamples(t, tt.wantMethod, tt.wantRoute) - samplesBefore; got != 1 {
				t.Errorf("duration histogram grew by %d samples, want 1", got)
			}
		})
	}
}

// Главное правило: в метке шаблон маршрута, а не URL. Иначе /books/1, /books/2, … давали бы
// по новому временному ряду на каждую книгу.
func TestMetrics_LabelIsTheRouteNotTheURL(t *testing.T) {
	mux := http.NewServeMux()
	mux.Handle("GET /books/{id}", RouteLabel("/t/books/{id}")(respondWith(http.StatusOK)))
	handler := Metrics()(mux)

	before := requestsTotal(http.MethodGet, "/t/books/{id}", http.StatusOK)
	for _, id := range []string{"1", "2", "3"} {
		handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/books/"+id, nil))
	}

	if got := requestsTotal(http.MethodGet, "/t/books/{id}", http.StatusOK) - before; got != 3 {
		t.Errorf("one series grew by %v, want 3", got)
	}
	for _, raw := range []string{"/books/1", "/books/2", "/books/3"} {
		if hasRouteLabel(t, raw) {
			t.Errorf("found a series labelled with the raw URL %q", raw)
		}
	}
}

func TestRouteLabel_WithoutMetrics(t *testing.T) {
	next := &spy{}

	rec := httptest.NewRecorder()
	RouteLabel("/anything")(next).ServeHTTP(rec, newRequest(http.MethodGet, "/"))

	if !next.called {
		t.Error("RouteLabel without Metrics above it must still pass the request on")
	}
}

func TestMetricsMethod(t *testing.T) {
	for _, m := range []string{"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} {
		if got := metricsMethod(m); got != m {
			t.Errorf("metricsMethod(%q) = %q, want it unchanged", m, got)
		}
	}
	for _, m := range []string{"FOO", "get", "TRACE", "CONNECT", ""} {
		if got := metricsMethod(m); got != "OTHER" {
			t.Errorf("metricsMethod(%q) = %q, want OTHER", m, got)
		}
	}
}
