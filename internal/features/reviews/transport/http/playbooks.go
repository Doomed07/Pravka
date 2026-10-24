package reviews_transport_http

import (
	"net/http"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

func (h *ReviewsHTTPHandler) Playbooks(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	pbs, err := h.service.Playbooks(r.Context())
	if err != nil {
		resp.ErrorResponse(err, "failed to list playbooks")
		return
	}
	out := playbooksDTOFromDomain(pbs)
	resp.JSONResponse(http.StatusOK, out)
}
