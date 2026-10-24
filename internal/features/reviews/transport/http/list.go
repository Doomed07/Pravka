package reviews_transport_http

import (
	"net/http"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_request "github.com/Doomed07/Pravka/internal/core/transport/http/request"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

func (h *ReviewsHTTPHandler) List(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	limit, offset, err := core_http_request.GetLimitOffsetQueryParam(r)
	if err != nil {
		resp.ErrorResponse(err, "invalid query")
		return
	}
	l, o := 0, 0
	if limit != nil {
		l = *limit
	}
	if offset != nil {
		o = *offset
	}
	revs, err := h.service.List(r.Context(), who.UserID, l, o)
	if err != nil {
		resp.ErrorResponse(err, "failed to list reviews")
		return
	}
	out := reviewsDTOFromDomain(revs)
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}
