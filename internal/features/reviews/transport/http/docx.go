package reviews_transport_http

import (
	"fmt"
	"net/http"
	"net/url"
)

// DOCX — единая версия в Word: правки контрагента и наши примечания.
func (h *ReviewsHTTPHandler) DOCX(rw http.ResponseWriter, r *http.Request) {
	data, id, ok := h.file(rw, r, "docx")
	if !ok {
		return
	}
	name := fmt.Sprintf("Правки_единая_версия_%d.docx", id)
	rw.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
	rw.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"pravki_%d.docx\"; filename*=UTF-8''%s", id, url.PathEscape(name)))
	rw.Header().Set("Cache-Control", "no-store")
	rw.WriteHeader(http.StatusOK)
	_, _ = rw.Write(data)
}
