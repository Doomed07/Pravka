package reviews_transport_http

import (
	"net/http"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

func (h *ReviewsHTTPHandler) Get(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	rev, err := h.service.Get(r.Context(), who.UserID, id)
	if err != nil {
		resp.ErrorResponse(err, "failed to get review")
		return
	}
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, reviewDTOFromDomain(rev))
}
