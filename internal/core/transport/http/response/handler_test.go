package core_http_response

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"go.uber.org/zap"
)

// zap.NewNop() — логгер, который ничего не пишет: в тесте нам не нужны
// ни файлы логов, ни вывод в консоль
func newTestLogger() *core_logger.Logger {
	return &core_logger.Logger{Logger: zap.NewNop()}
}

func TestHTTPResponseHandler_ErrorResponse(t *testing.T) {
	tests := []struct {
		name       string
		err        error
		wantStatus int
	}{
		{name: "invalid argument", err: core_errors.ErrInvalidArgument, wantStatus: http.StatusBadRequest},
		{name: "not found", err: core_errors.ErrNotFound, wantStatus: http.StatusNotFound},
		{name: "conflict", err: core_errors.ErrConflict, wantStatus: http.StatusConflict},
		{name: "unauthorized", err: core_errors.ErrUnauthorized, wantStatus: http.StatusUnauthorized},
		{name: "forbidden", err: core_errors.ErrForbidden, wantStatus: http.StatusForbidden},
		{
			name:       "wrapped not found",
			err:        fmt.Errorf("get user: %w", fmt.Errorf("repo: %w", core_errors.ErrNotFound)),
			wantStatus: http.StatusNotFound,
		},
		{name: "unknown error", err: errors.New("db is down"), wantStatus: http.StatusInternalServerError},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// httptest.ResponseRecorder запоминает статус и тело ответа
			rec := httptest.NewRecorder()
			h := NewHTTPResponseHandler(newTestLogger(), rec)

			h.ErrorResponse(tt.err, "failed to do something")

			if rec.Code != tt.wantStatus {
				t.Errorf("status = %d, want %d", rec.Code, tt.wantStatus)
			}

			var body ErrorResponse
			if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
				t.Fatalf("decode response body: %v", err)
			}
			if body.Error != tt.err.Error() || body.Message != "failed to do something" {
				t.Errorf("body = %+v, want error=%q message=%q", body, tt.err.Error(), "failed to do something")
			}
		})
	}
}

func TestHTTPResponseHandler_PanicResponse(t *testing.T) {
	rec := httptest.NewRecorder()
	h := NewHTTPResponseHandler(newTestLogger(), rec)

	h.PanicResponse("boom", "panic in handler")

	if rec.Code != http.StatusInternalServerError {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}
}
