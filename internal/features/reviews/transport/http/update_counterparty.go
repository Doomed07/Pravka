package reviews_transport_http

import (
	"net/http"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_request "github.com/Doomed07/Pravka/internal/core/transport/http/request"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type UpdateCounterpartyRequest struct {
	Name string `json:"name"`
	INN  string `json:"inn"`
}

func (r UpdateCounterpartyRequest) Validate() error { return nil } // название и ИНН проверяет core_domain в сервисе

// UpdateCounterparty — переименовать контрагента и/или поправить его ИНН.
func (h *ReviewsHTTPHandler) UpdateCounterparty(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	var req UpdateCounterpartyRequest
	if err := core_http_request.DecodeAndValidateRequest(r, &req); err != nil {
		resp.ErrorResponse(err, "invalid counterparty")
		return
	}
	if err := h.service.RenameCounterparty(r.Context(), who.UserID, id, req.Name, req.INN); err != nil {
		resp.ErrorResponse(err, "failed to update counterparty")
		return
	}
	resp.StatusCodeResponse(http.StatusNoContent)
}
