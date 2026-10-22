package core_http_response

import (
	"encoding/json"
	"fmt"
	"net/http"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	"go.uber.org/zap"
)

type HTTPResponseHandler struct {
	log *core_logger.Logger
	rw  http.ResponseWriter
}

func NewHTTPResponseHandler(
	log *core_logger.Logger,
	rw http.ResponseWriter,
) *HTTPResponseHandler {
	return &HTTPResponseHandler{
		log: log,
		rw:  rw,
	}
}

func (h *HTTPResponseHandler) JSONResponse(statusCode int, responseBody any) {
	h.rw.WriteHeader(statusCode)

	if err := json.NewEncoder(h.rw).Encode(responseBody); err != nil {
		h.log.Error("write HTTP response", zap.Error(err))
	}
}

func (h *HTTPResponseHandler) StatusCodeResponse(statusCode int) {
	h.rw.WriteHeader(statusCode)
}

func (h *HTTPResponseHandler) ErrorResponse(err error, msg string) {
	statusCode := StatusFromError(err)

	logFunc := h.log.Error
	switch statusCode {
	case http.StatusConflict, http.StatusBadRequest,
		http.StatusUnauthorized, http.StatusForbidden:
		logFunc = h.log.Warn
	case http.StatusNotFound:
		logFunc = h.log.Debug
	}

	logFunc(msg, zap.Error(err))

	h.errorResponse(statusCode, err, msg)
}

func (h *HTTPResponseHandler) PanicResponse(p any, msg string) {
	statusCode := http.StatusInternalServerError
	err := fmt.Errorf("unexpected panic: %v", p)

	h.log.Error(msg, zap.Error(err))

	h.errorResponse(statusCode, err, msg)
}

func (h *HTTPResponseHandler) errorResponse(statusCode int, err error, msg string) {
	response := ErrorResponse{
		Error:   err.Error(),
		Message: msg,
	}

	h.JSONResponse(statusCode, response)
}
