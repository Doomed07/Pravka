package reviews_transport_http

import (
	"net/http"
)

func (h *ReviewsHTTPHandler) Changes(rw http.ResponseWriter, r *http.Request) {
	h.json(rw, r, "changes")
}
