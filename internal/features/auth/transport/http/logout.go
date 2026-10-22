package auth_transport_http

import (
	"net/http"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

// Logout       godoc
// @Summary     Logout
// @Description Delete the current session and clear the session cookie. Login is not required: without a session the response is still 204.
// @Description Requests must carry `Content-Type: application/json`, even with an empty body.
// @Tags        auth
// @Accept      json
// @Success     204 "Signed out, session cookie cleared"
// @Failure     400 {object} core_http_response.ErrorResponse "Content-Type is not application/json"
// @Failure     403 {object} core_http_response.ErrorResponse "Cross-site request"
// @Failure     500 {object} core_http_response.ErrorResponse "Internal server error"
// @Router      /auth/logout [post]
func (h *AuthHTTPHandler) Logout(rw http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	log := core_logger.FromCtx(ctx)
	responseHandler := core_http_response.NewHTTPResponseHandler(log, rw)

	http.SetCookie(rw, core_auth.ClearSessionCookie(h.secure)) // очищаем у браузера в любом случае
	rw.Header().Set("Cache-Control", "no-store")

	if cookie, err := r.Cookie(core_auth.SessionCookieName); err == nil {
		if err := h.authService.Logout(ctx, cookie.Value); err != nil {
			responseHandler.ErrorResponse(err, "failed to logout")
			return
		}
	}

	responseHandler.StatusCodeResponse(http.StatusNoContent)
}
