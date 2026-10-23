package core_http_middleware

import (
	"context"
	"errors"
	"fmt"
	"net/http"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_request "github.com/Doomed07/Pravka/internal/core/transport/http/request"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type Authenticator interface {
	Authenticate(ctx context.Context, token string) (core_domain.User, error)
}

func Authenticate(a Authenticator) Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			cookie, err := r.Cookie(core_auth.SessionCookieName)
			if err != nil || cookie.Value == "" {
				next.ServeHTTP(w, r) // гость: БД не трогаем
				return
			}

			ctx := r.Context()
			user, err := a.Authenticate(ctx, cookie.Value)
			if err != nil {
				if errors.Is(err, core_errors.ErrUnauthorized) {
					next.ServeHTTP(w, r) // токен подделан, просрочен или удалён: тоже гость
					return
				}

				deny(w, r, err, "failed to authenticate")
				return // БД упала: дальше не идём
			}

			ctx = core_auth.WithIdentity(ctx, core_auth.Identity{
				UserID:   user.ID,
				Username: user.Username,
				Email:    user.Email,
			})
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func RequireAuth() Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if _, ok := core_auth.IdentityFromCtx(r.Context()); !ok {
				deny(w, r,
					fmt.Errorf("authentication required: %w", core_errors.ErrUnauthorized),
					"not authenticated")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

func RequireSelf(param string) Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			identity, ok := core_auth.IdentityFromCtx(r.Context())
			if !ok {
				deny(w, r,
					fmt.Errorf("authentication required: %w", core_errors.ErrUnauthorized),
					"not authenticated")
				return
			}
			id, err := core_http_request.GetIntPathParam(r, param)
			if err != nil {
				deny(w, r, err, "invalid path parameter")
				return
			}
			if identity.UserID != id {
				deny(w, r,
					fmt.Errorf("user %d may not act on user %d: %w",
						identity.UserID, id, core_errors.ErrForbidden),
					"forbidden")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// deny отвечает ошибкой так же, как обработчики: через ErrorResponse, значит и логируется так же.
func deny(w http.ResponseWriter, r *http.Request, err error, msg string) {
	ctx := r.Context()
	log := core_logger.FromCtx(ctx)
	responseHandler := core_http_response.NewHTTPResponseHandler(log, w)
	responseHandler.ErrorResponse(err, msg)
}
