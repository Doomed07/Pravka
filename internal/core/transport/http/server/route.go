package core_http_server

import (
	"net/http"

	core_http_middleware "github.com/Doomed07/Pravka/internal/core/transport/http/middleware"
)

type Route struct {
	Method      string
	Path        string
	Handler     http.HandlerFunc
	Middlewares []core_http_middleware.Middleware
}

func (r *Route) WithMiddleware() http.Handler {
	return core_http_middleware.ChainMiddleware(
		r.Handler, r.Middlewares...,
	)
}
