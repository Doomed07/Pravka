package reviews_transport_http

import (
	"net/http"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_request "github.com/Doomed07/Pravka/internal/core/transport/http/request"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type SaveChoiceRequest struct {
	Choice string `json:"choice"`
	Text   string `json:"text"`
}

func (r SaveChoiceRequest) Validate() error { return nil } // проверяет core_domain.ReviewChoice в сервисе

func (h *ReviewsHTTPHandler) SaveChoice(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	var req SaveChoiceRequest
	if err := core_http_request.DecodeAndValidateRequest(r, &req); err != nil {
		resp.ErrorResponse(err, "invalid choice")
		return
	}
	c := core_domain.ReviewChoice{ChangeID: r.PathValue("change"), Choice: req.Choice, Text: req.Text}
	if err := h.service.SaveChoice(r.Context(), who.UserID, id, c); err != nil {
		resp.ErrorResponse(err, "failed to save choice")
		return
	}
	resp.StatusCodeResponse(http.StatusNoContent)
}
