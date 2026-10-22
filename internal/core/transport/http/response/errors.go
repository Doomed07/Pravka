package core_http_response

import (
	"errors"
	"net/http"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

type ErrorResponse struct {
	Error   string `json:"error" example:"invalid argument"`
	Message string `json:"message" example:"the provided argument is invalid"`
}

// StatusFromError переводит ошибку сервиса в HTTP-статус. Порядок проверок важен:
// ошибка может оборачивать несколько sentinel-ошибок сразу.
func StatusFromError(err error) int {
	switch {
	case errors.Is(err, core_errors.ErrConflict):
		return http.StatusConflict
	case errors.Is(err, core_errors.ErrInvalidArgument):
		return http.StatusBadRequest
	case errors.Is(err, core_errors.ErrNotFound):
		return http.StatusNotFound
	case errors.Is(err, core_errors.ErrUnauthorized):
		return http.StatusUnauthorized
	case errors.Is(err, core_errors.ErrForbidden):
		return http.StatusForbidden
	case errors.Is(err, core_errors.ErrUnprocessable):
		return http.StatusUnprocessableEntity
	case errors.Is(err, core_errors.ErrUnavailable):
		return http.StatusBadGateway
	default:
		return http.StatusInternalServerError
	}
}
