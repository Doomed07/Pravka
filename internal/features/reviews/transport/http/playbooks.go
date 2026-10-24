package reviews_transport_http

import (
	"net/http"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type PlaybookDTO struct {
	Key  string `json:"key"`
	Name string `json:"name"`
	Role string `json:"role"`
}

func (h *ReviewsHTTPHandler) Playbooks(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	pbs, err := h.service.Playbooks(r.Context())
	if err != nil {
		resp.ErrorResponse(err, "failed to list playbooks")
		return
	}
	out := playbooksDTOFromDomain(pbs)
	resp.JSONResponse(http.StatusOK, out)
}

func playbookDTOFromDomain(p core_domain.Playbook) PlaybookDTO {
	return PlaybookDTO{Key: p.Key, Name: p.Name, Role: p.Role}
}

func playbooksDTOFromDomain(list []core_domain.Playbook) []PlaybookDTO {
	out := make([]PlaybookDTO, len(list))
	for i, x := range list {
		out[i] = playbookDTOFromDomain(x)
	}
	return out
}
