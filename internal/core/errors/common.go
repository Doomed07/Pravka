package core_errors

import "errors"

var (
	ErrNotFound        = errors.New("not found")
	ErrInvalidArgument = errors.New("invalid argument")
	ErrConflict        = errors.New("conflict")
	ErrUnauthorized    = errors.New("unauthorized")
	ErrForbidden       = errors.New("forbidden")
	// ErrUnprocessable — запрос понятен, но выполнить его нельзя без решения человека (сторона договора не подтверждена).
	ErrUnprocessable = errors.New("unprocessable")
	// ErrUnavailable — внешний сервис (движок разбора) не отвечает.
	ErrUnavailable = errors.New("service unavailable")
)
