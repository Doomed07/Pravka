package reviews_transport_http

import (
	"net/http"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type WordingDTO struct {
	ChangeID   string    `json:"change_id"`
	ReviewID   int       `json:"review_id"`
	TheirsName string    `json:"theirs_name"`
	CreatedAt  time.Time `json:"created_at"`
	Clause     string    `json:"clause"`
	Text       string    `json:"text"`
	Distance   float64   `json:"distance"`
}

func (h *ReviewsHTTPHandler) Wordings(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	list, err := h.service.Wordings(r.Context(), who.UserID, id)
	if err != nil {
		resp.ErrorResponse(err, "failed to list wordings")
		return
	}
	out := wordingsDTOFromDomain(list)
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}

func wordingDTOFromDomain(w core_domain.Wording) WordingDTO {
	return WordingDTO{ChangeID: w.ChangeID, ReviewID: w.ReviewID, TheirsName: w.TheirsName, CreatedAt: w.CreatedAt,
		Clause: w.Clause, Text: w.Text, Distance: w.Distance}
}

func wordingsDTOFromDomain(list []core_domain.Wording) []WordingDTO {
	out := make([]WordingDTO, len(list))
	for i, x := range list {
		out[i] = wordingDTOFromDomain(x)
	}
	return out
}
