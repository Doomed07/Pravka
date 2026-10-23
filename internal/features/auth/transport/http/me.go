package auth_transport_http

import (
	"fmt"
	"net/http"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
)

// Me           godoc
// @Summary     Current user
// @Description Return the signed-in user, including the email (the email is visible only to its owner). Requires the session cookie.
// @Tags        auth
// @Produce     json
// @Success     200 {object} UserDTOResponse "Current user"
// @Failure     401 {object} core_http_response.ErrorResponse "Not signed in"
// @Router      /auth/me [get]
func (h *AuthHTTPHandler) Me(rw http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	log := core_logger.FromCtx(ctx)
	responseHandler := core_http_response.NewHTTPResponseHandler(log, rw)

	identity, ok := core_auth.IdentityFromCtx(ctx)
	if !ok {
		responseHandler.ErrorResponse(fmt.Errorf(
			"not logged in: %w", core_errors.ErrUnauthorized), "not authenticated")
		return
	}
	rw.Header().Set("Cache-Control", "no-store")
	responseHandler.JSONResponse(http.StatusOK, UserDTOResponse{
		ID:       identity.UserID,
		Username: identity.Username,
		Email:    identity.Email,
	})
}
