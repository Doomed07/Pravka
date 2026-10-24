package reviews_transport_http

import (
	"fmt"
	"net/http"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

// DetectParties — стороны договора и контрагент по первой версии (поля: theirs — файл, company — ИНН или наименование нашей
// компании). Ничего не сохраняет: форма главной показывает найденное, юрист подтверждает или правит.
func (h *ReviewsHTTPHandler) DetectParties(rw http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(ctx), rw)
	if _, ok := identity(r, resp); !ok {
		return
	}
	r.Body = http.MaxBytesReader(rw, r.Body, core_domain.MaxUploadBytes+(1<<20))
	if err := r.ParseMultipartForm(8 << 20); err != nil {
		resp.ErrorResponse(fmt.Errorf("форма не разобрана (файл больше 30 МБ?): %v: %w", err, core_errors.ErrInvalidArgument), "invalid upload")
		return
	}
	defer func() { _ = r.MultipartForm.RemoveAll() }()
	theirs, err := readFile(r.MultipartForm, "theirs")
	if err != nil {
		resp.ErrorResponse(err, "invalid upload")
		return
	}
	if theirs == nil {
		resp.ErrorResponse(fmt.Errorf("загрузите договор: %w", core_errors.ErrInvalidArgument), "invalid upload")
		return
	}
	found, err := h.service.DetectParties(ctx, *theirs, r.FormValue("company"))
	if err != nil {
		resp.ErrorResponse(err, "failed to detect parties")
		return
	}
	out := detectedPartiesDTOFromDomain(found)
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}
