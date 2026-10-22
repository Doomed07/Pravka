package auth_transport_http

import (
	"net/http"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_request "github.com/Doomed07/Pravka/internal/core/transport/http/request"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type LoginRequest struct {
	Login    string `json:"login" validate:"required" example:"book_worm07 or lol@mail.com"`
	Password string `json:"password" validate:"required" example:"LoveBooks01!"`
}

type LoginResponse UserDTOResponse

// Login        godoc
// @Summary     Login
// @Description Sign in by username or email (a login with `@` is treated as email) and password.
// @Description On success the response sets the HttpOnly session cookie `pravki_session`; every login issues a new token.
// @Description Wrong login and wrong password produce the same 401 response.
// @Tags        auth
// @Accept      json
// @Produce     json
// @Param       request body LoginRequest true "Login request body"
// @Success     200 {object} LoginResponse "Signed in, session cookie set"
// @Failure     400 {object} core_http_response.ErrorResponse "Bad request"
// @Failure     401 {object} core_http_response.ErrorResponse "Invalid login or password"
// @Failure     500 {object} core_http_response.ErrorResponse "Internal server error"
// @Router      /auth/login [post]
func (h *AuthHTTPHandler) Login(rw http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	log := core_logger.FromCtx(ctx)
	responseHandler := core_http_response.NewHTTPResponseHandler(log, rw)

	var login LoginRequest
	if err := core_http_request.DecodeAndValidateRequest(r, &login); err != nil {
		responseHandler.ErrorResponse(err, "failed to decode and validate HTTP request")
		return
	}

	user, token, err := h.authService.Login(ctx, login.Login, login.Password)
	if err != nil {
		responseHandler.ErrorResponse(err, "failed to login")
		return
	}

	rw.Header().Set("Cache-Control", "no-store")
	http.SetCookie(rw, core_auth.NewSessionCookie(token, h.ttl, h.secure))

	response := LoginResponse(userDTOFromDomain(user))
	responseHandler.JSONResponse(http.StatusOK, response)
}
