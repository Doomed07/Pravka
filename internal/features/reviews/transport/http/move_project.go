package reviews_transport_http

import (
	"net/http"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_request "github.com/Doomed07/Pravka/internal/core/transport/http/request"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type MoveProjectRequest struct {
	CounterpartyID int `json:"counterparty_id"`
}

func (r MoveProjectRequest) Validate() error { return nil } // номер проверяет сервис

// MoveProject — перенести договор к другому контрагенту.
func (h *ReviewsHTTPHandler) MoveProject(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	var req MoveProjectRequest
	if err := core_http_request.DecodeAndValidateRequest(r, &req); err != nil {
		resp.ErrorResponse(err, "invalid project move")
		return
	}
	if err := h.service.MoveProject(r.Context(), who.UserID, id, req.CounterpartyID); err != nil {
		resp.ErrorResponse(err, "failed to move project")
		return
	}
	resp.StatusCodeResponse(http.StatusNoContent)
}
