package core_http_middleware

import (
	"fmt"
	"mime"
	"net/http"
	"net/url"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

// UploadMarker — значение заголовка X-Requested-With, с которым наш фронтенд загружает файлы.
const UploadMarker = "pravki"

func SameOrigin() Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			switch r.Method {
			case http.MethodGet, http.MethodHead, http.MethodOptions:
				next.ServeHTTP(w, r) // безопасные методы данных не меняют
				return
			}

			// 1. Браузер сам сообщает, откуда запрос. same-origin — наш сайт, none — адресная строка.
			if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" && site != "none" {
				deny(w, r,
					fmt.Errorf("cross-site request (Sec-Fetch-Site=%s): %w",
						site, core_errors.ErrForbidden),
					"forbidden")
				return
			}

			// 2. Origin, если он есть, должен указывать на тот же хост, на который пришёл запрос.
			if origin := r.Header.Get("Origin"); origin != "" {
				u, err := url.Parse(origin)
				if origin == "null" || err != nil || u.Host != r.Host {
					deny(w, r,
						fmt.Errorf("foreign origin: %w", core_errors.ErrForbidden),
						"forbidden")
					return
				}
			}

			// 3. Для POST/PATCH требуем JSON. Исключение — загрузка файлов (multipart/form-data) с заголовком
			// X-Requested-With: pravki: чужой сайт не может отправить такой заголовок без разрешения CORS.
			if r.Method == http.MethodPost || r.Method == http.MethodPatch {
				mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
				upload := err == nil && mediaType == "multipart/form-data" && r.Header.Get("X-Requested-With") == UploadMarker
				if !upload && (err != nil || mediaType != "application/json") {
					deny(w, r,
						fmt.Errorf("content type must be application/json: %w",
							core_errors.ErrInvalidArgument),
						"unsupported content type")
					return
				}
			}

			next.ServeHTTP(w, r)
		})
	}
}
