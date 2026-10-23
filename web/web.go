// Package web хранит фронтенд «Правок»: HTML-страницы, CSS, картинки и JS.
// Страницы — статичные каркасы, данные в них подгружает JS из /api/v1.
// Файлы встраиваются в бинарник, поэтому в Docker-образ их копировать не нужно.
package web

import (
	"embed"
	"io/fs"
	"net/http"
	"strings"

	core_http_server "github.com/Doomed07/Pravka/internal/core/transport/http/server"
)

//go:embed static
var files embed.FS

// Static — всё содержимое web/static, раздаётся по /static/.
func Static() fs.FS {
	static, err := fs.Sub(files, "static")
	if err != nil {
		panic(err)
	}
	return static
}

// Routes — адреса страниц сайта. Каждая страница — HTML-файл; данные подгружает JS из /api/v1.
// Права доступа проверяет API: страница разбора чужого пользователя покажет 404 из API.
func Routes() []core_http_server.Route {
	return []core_http_server.Route{
		{
			// {$} — только сам "/": шаблон "GET /" конфликтовал бы с "/api/v1/"
			Method:  http.MethodGet,
			Path:    "/{$}",
			Handler: page("index.html", http.StatusOK),
		},
		{
			Method:  http.MethodGet,
			Path:    "/reviews/{id}",
			Handler: page("review.html", http.StatusOK),
		},
		{
			Method:  http.MethodGet,
			Path:    "/signup",
			Handler: page("signup.html", http.StatusOK),
		},
		{
			Method:  http.MethodGet,
			Path:    "/login",
			Handler: page("login.html", http.StatusOK),
		},
		{
			Method:  http.MethodGet,
			Path:    "/about",
			Handler: page("about.html", http.StatusOK),
		},
		{
			// без метода: всё, что не совпало ни с чем другим
			Path:    "/",
			Handler: notFound(page("404.html", http.StatusNotFound)),
		},
	}
}

func page(name string, statusCode int) http.HandlerFunc {
	return func(rw http.ResponseWriter, r *http.Request) {
		body, err := fs.ReadFile(files, "static/"+name)
		if err != nil {
			http.Error(rw, http.StatusText(http.StatusInternalServerError), http.StatusInternalServerError)
			return
		}

		rw.Header().Set("Content-Type", "text/html; charset=utf-8")
		rw.Header().Set("X-Content-Type-Options", "nosniff")
		rw.WriteHeader(statusCode)
		_, _ = rw.Write(body)
	}
}

// notFound: неизвестные пути API отвечают обычным текстовым 404, как и раньше.
func notFound(htmlPage http.HandlerFunc) http.HandlerFunc {
	return func(rw http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api" || strings.HasPrefix(r.URL.Path, "/api/") {
			http.NotFound(rw, r)
			return
		}

		htmlPage(rw, r)
	}
}
