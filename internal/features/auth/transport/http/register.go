package auth_transport_http

import (
	"crypto/subtle"
	"fmt"
	"net/http"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_request "github.com/Doomed07/Pravka/internal/core/transport/http/request"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

type RegisterRequest struct {
	Username string `json:"username" validate:"required" example:"lawyer_01"`
	Email    string `json:"email" validate:"required" example:"lol@mail.com"`
	Password string `json:"password" validate:"required" example:"Contracts01!"`
	// InviteCode обязателен, если на сервере задан AUTH_SIGNUP_CODE.
	InviteCode string `json:"invite_code"`
}

type RegisterResponse UserDTOResponse

// Register     godoc
// @Summary     Register
// @Description Create a new account and sign in. On success the response sets the HttpOnly session cookie `pravki_session`.
// @Description Username: 3-30 chars, latin letters, digits and `_`, unique case-insensitively. Email is stored in lower case.
// @Description Password: 8-72 printable ASCII chars (latin letters, digits, symbols; no spaces), must not equal the username.
// @Tags        auth
// @Accept      json
// @Produce     json
// @Param       request body RegisterRequest true "Register request body"
// @Success     201 {object} RegisterResponse "Account created, session cookie set"
// @Failure     400 {object} core_http_response.ErrorResponse "Bad request"
// @Failure     409 {object} core_http_response.ErrorResponse "Username or email is already taken"
// @Failure     500 {object} core_http_response.ErrorResponse "Internal server error"
// @Router      /auth/register [post]
func (h *AuthHTTPHandler) Register(rw http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	log := core_logger.FromCtx(ctx)
	responseHandler := core_http_response.NewHTTPResponseHandler(log, rw)

	var reg RegisterRequest
	if err := core_http_request.DecodeAndValidateRequest(r, &reg); err != nil {
		responseHandler.ErrorResponse(err, "failed to decode and validate HTTP request")
		return
	}

	if h.signupCode != "" && subtle.ConstantTimeCompare([]byte(reg.InviteCode), []byte(h.signupCode)) != 1 {
		responseHandler.ErrorResponse(fmt.Errorf("invalid invite code: %w", core_errors.ErrForbidden), "invalid invite code")
		return
	}

	user, token, err := h.authService.Register(ctx, reg.Username, reg.Email, reg.Password)
	if err != nil {
		responseHandler.ErrorResponse(err, "failed to register")
		return
	}

	rw.Header().Set("Cache-Control", "no-store")
	http.SetCookie(rw, core_auth.NewSessionCookie(token, h.ttl, h.secure))

	response := RegisterResponse(userDTOFromDomain(user))
	responseHandler.JSONResponse(http.StatusCreated, response)
}
