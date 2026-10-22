package core_http_middleware

import (
	"context"
	"net/http"
	"strconv"
	"time"

	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

// unmatchedRoute — метка для запросов, которые не дошли ни до одного маршрута
// (404 от mux, отказ SameOrigin до маршрута и т.п.).
const unmatchedRoute = "unmatched"

type routeLabelKey struct{}

// Metrics считает запросы и время ответа. Шаблон маршрута узнаёт не из URL,
// а из «ячейки» в контексте, которую заполняет RouteLabel на самом маршруте.
func Metrics() Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			route := new(string)
			ctx := context.WithValue(r.Context(), routeLabelKey{}, route)
			rw := core_http_response.NewHTTPResponseWriter(w)
			start := time.Now()

			next.ServeHTTP(rw, r.WithContext(ctx))

			label := *route
			if label == "" {
				label = unmatchedRoute
			}
			method := metricsMethod(r.Method)

			core_metrics.HTTPRequestDuration.
				WithLabelValues(method, label).
				Observe(time.Since(start).Seconds())
			core_metrics.HTTPRequestsTotal.
				WithLabelValues(method, label, strconv.Itoa(rw.GetStatusCode())).
				Inc()
		})
	}
}

// RouteLabel записывает шаблон маршрута в ячейку, созданную Metrics.
// Без Metrics выше по цепочке (например, в тестах) ничего не делает.
func RouteLabel(pattern string) Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if route, ok := r.Context().Value(routeLabelKey{}).(*string); ok {
				*route = pattern
			}
			next.ServeHTTP(w, r)
		})
	}
}

// metricsMethod оставляет как есть только известные методы. Метод присылает клиент:
// без этого запрос с методом "AAAA1", "AAAA2"… создавал бы новые временные ряды.
func metricsMethod(m string) string {
	switch m {
	case http.MethodGet, http.MethodHead, http.MethodPost, http.MethodPut,
		http.MethodPatch, http.MethodDelete, http.MethodOptions:
		return m
	}
	return "OTHER"
}
