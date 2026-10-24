package reviews_transport_http

import (
	"net/http"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

// Project — история договора: раунды и что в каждом нового.
func (h *ReviewsHTTPHandler) Project(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	view, err := h.service.Project(r.Context(), who.UserID, id)
	if err != nil {
		resp.ErrorResponse(err, "failed to get project")
		return
	}
	out := projectViewDTOFromDomain(view)
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}
