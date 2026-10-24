package reviews_transport_http

import (
	"net/http"
)

// Document — единая версия договора: абзацы с правками для страницы разбора.
func (h *ReviewsHTTPHandler) Document(rw http.ResponseWriter, r *http.Request) {
	h.json(rw, r, "document")
}
