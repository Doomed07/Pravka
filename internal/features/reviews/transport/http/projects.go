package reviews_transport_http

import (
	"net/http"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

// Projects — договоры пользователя: для выбора договора в форме нового разбора.
func (h *ReviewsHTTPHandler) Projects(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	list, err := h.service.Projects(r.Context(), who.UserID)
	if err != nil {
		resp.ErrorResponse(err, "failed to list projects")
		return
	}
	out := projectsDTOFromDomain(list)
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}
