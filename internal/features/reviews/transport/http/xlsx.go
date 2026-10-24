package reviews_transport_http

import (
	"fmt"
	"net/http"
	"net/url"
)

func (h *ReviewsHTTPHandler) XLSX(rw http.ResponseWriter, r *http.Request) {
	data, id, ok := h.file(rw, r, "xlsx")
	if !ok {
		return
	}
	name := fmt.Sprintf("Правки_разбор_%d.xlsx", id)
	rw.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	rw.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"pravki_%d.xlsx\"; filename*=UTF-8''%s", id, url.PathEscape(name)))
	rw.Header().Set("Cache-Control", "no-store")
	rw.WriteHeader(http.StatusOK)
	_, _ = rw.Write(data)
}
