package reviews_transport_http

import (
	"net/http"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type ChoiceDTO struct {
	ChangeID string `json:"change_id"`
	Choice   string `json:"choice"`
	Text     string `json:"text"`
}

func (h *ReviewsHTTPHandler) Choices(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	list, err := h.service.Choices(r.Context(), who.UserID, id)
	if err != nil {
		resp.ErrorResponse(err, "failed to list choices")
		return
	}
	out := choicesDTOFromDomain(list)
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}

func choiceDTOFromDomain(c core_domain.ReviewChoice) ChoiceDTO {
	return ChoiceDTO{ChangeID: c.ChangeID, Choice: c.Choice, Text: c.Text}
}

func choicesDTOFromDomain(list []core_domain.ReviewChoice) []ChoiceDTO {
	out := make([]ChoiceDTO, len(list))
	for i, x := range list {
		out[i] = choiceDTOFromDomain(x)
	}
	return out
}
