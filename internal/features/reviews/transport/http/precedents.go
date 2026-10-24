package reviews_transport_http

import (
	"net/http"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type PrecedentDTO struct {
	ChangeID   string    `json:"change_id"`
	ReviewID   int       `json:"review_id"`
	PastChange string    `json:"past_change"`
	TheirsName string    `json:"theirs_name"`
	CreatedAt  time.Time `json:"created_at"`
	Clause     string    `json:"clause"`
	Topic      string    `json:"topic"`
	Before     string    `json:"before"`
	After      string    `json:"after"`
	Choice     string    `json:"choice"`
	Text       string    `json:"text"`
	Same       bool      `json:"same"`
	Semantic   bool      `json:"semantic"`
	Score      float64   `json:"score"`
}

func (h *ReviewsHTTPHandler) Precedents(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	list, err := h.service.Precedents(r.Context(), who.UserID, id)
	if err != nil {
		resp.ErrorResponse(err, "failed to list precedents")
		return
	}
	out := precedentsDTOFromDomain(list)
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}

func precedentDTOFromDomain(p core_domain.Precedent) PrecedentDTO {
	return PrecedentDTO{ChangeID: p.ChangeID, ReviewID: p.ReviewID, PastChange: p.PastChangeID, TheirsName: p.TheirsName, CreatedAt: p.CreatedAt,
		Clause: p.Clause, Topic: p.Topic, Before: p.Before, After: p.After, Choice: p.Choice, Text: p.Text, Same: p.Same, Semantic: p.Semantic,
		Score: p.Score}
}

func precedentsDTOFromDomain(list []core_domain.Precedent) []PrecedentDTO {
	out := make([]PrecedentDTO, len(list))
	for i, x := range list {
		out[i] = precedentDTOFromDomain(x)
	}
	return out
}
