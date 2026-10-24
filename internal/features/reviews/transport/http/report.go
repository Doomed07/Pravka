package reviews_transport_http

import (
	"net/http"
)

// Report отдаёт HTML-отчёт движка. Отчёт строится из текста чужого договора, поэтому скрипты в нём запрещены CSP.
func (h *ReviewsHTTPHandler) Report(rw http.ResponseWriter, r *http.Request) {
	data, _, ok := h.file(rw, r, "html")
	if !ok {
		return
	}
	rw.Header().Set("Content-Type", "text/html; charset=utf-8")
	rw.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'")
	rw.Header().Set("X-Content-Type-Options", "nosniff")
	rw.Header().Set("Cache-Control", "no-store")
	rw.WriteHeader(http.StatusOK)
	_, _ = rw.Write(data)
}
