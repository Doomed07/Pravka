package reviews_transport_http

import (
	"net/http"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type LawHintDTO struct {
	ChangeID string  `json:"change_id"`
	Article  string  `json:"article"`
	Point    string  `json:"point"`
	Title    string  `json:"title"`
	Chapter  string  `json:"chapter"`
	Edited   string  `json:"edited"`
	Text     string  `json:"text"`
	Distance float64 `json:"distance"`
}

func (h *ReviewsHTTPHandler) LawHints(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	list, err := h.service.LawHints(r.Context(), who.UserID, id)
	if err != nil {
		resp.ErrorResponse(err, "failed to list law hints")
		return
	}
	out := lawHintsDTOFromDomain(list)
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}

func lawHintDTOFromDomain(l core_domain.LawHint) LawHintDTO {
	return LawHintDTO{ChangeID: l.ChangeID, Article: l.Article, Point: l.Point, Title: l.Title, Chapter: l.Chapter,
		Edited: l.Edited, Text: l.Text, Distance: l.Distance}
}

func lawHintsDTOFromDomain(list []core_domain.LawHint) []LawHintDTO {
	out := make([]LawHintDTO, len(list))
	for i, x := range list {
		out[i] = lawHintDTOFromDomain(x)
	}
	return out
}
