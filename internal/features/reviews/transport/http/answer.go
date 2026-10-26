package reviews_transport_http

import (
	"fmt"
	"net/http"
	"net/url"

	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_request "github.com/Doomed07/Pravka/internal/core/transport/http/request"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type AnswerRequest struct {
	Author string `json:"author"`
}

func (r AnswerRequest) Validate() error { return nil }

// Answer отдаёт ответ контрагенту в Word. Файл не сохраняется: собирается по текущим решениям юриста.
func (h *ReviewsHTTPHandler) Answer(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	var req AnswerRequest
	if err := core_http_request.DecodeAndValidateRequest(r, &req); err != nil {
		resp.ErrorResponse(err, "invalid answer request")
		return
	}
	res, err := h.service.Answer(r.Context(), who.UserID, id, req.Author)
	if err != nil {
		resp.ErrorResponse(err, "failed to build answer")
		return
	}
	name := fmt.Sprintf("Правки_ответ_контрагенту_%d.docx", id)
	rw.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
	rw.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"pravki_answer_%d.docx\"; filename*=UTF-8''%s", id, url.PathEscape(name)))
	rw.Header().Set("Cache-Control", "no-store")
	// счётчики применённых решений; «без отметки» — решения по правкам, которых в рецензировании Word нет
	for k, header := range map[string]string{"accept": "accept", "reject": "reject", "counter": "counter", "reply": "reply", "edit": "edit", "comment": "comment",
		"без отметки": "untracked"} {
		if v, ok := res.Stats[k]; ok {
			rw.Header().Set("X-Pravki-"+header, fmt.Sprint(v))
		}
	}
	rw.WriteHeader(http.StatusOK)
	_, _ = rw.Write(res.DOCX)
}
