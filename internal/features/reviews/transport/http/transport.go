package reviews_transport_http

import (
	"context"
	"fmt"
	"net/http"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_middleware "github.com/Doomed07/Pravka/internal/core/transport/http/middleware"
	core_http_request "github.com/Doomed07/Pravka/internal/core/transport/http/request"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
	core_http_server "github.com/Doomed07/Pravka/internal/core/transport/http/server"
	"github.com/Doomed07/Pravka/internal/engine"
)

type ReviewsService interface {
	Playbooks(ctx context.Context) ([]core_domain.Playbook, error)
	Create(ctx context.Context, userID int, req core_domain.ReviewRequest) (core_domain.ContractReview, error)
	List(ctx context.Context, userID, limit, offset int) ([]core_domain.ContractReview, error)
	Get(ctx context.Context, userID, id int) (core_domain.ContractReview, error)
	File(ctx context.Context, userID, id int, kind string) ([]byte, error)
	Delete(ctx context.Context, userID, id int) error
	Choices(ctx context.Context, userID, id int) ([]core_domain.ReviewChoice, error)
	SaveChoice(ctx context.Context, userID, id int, c core_domain.ReviewChoice) error
	Precedents(ctx context.Context, userID, id int) ([]core_domain.Precedent, error)
	LawHints(ctx context.Context, userID, id int) ([]core_domain.LawHint, error)
	Wordings(ctx context.Context, userID, id int) ([]core_domain.Wording, error)
	Summary(ctx context.Context, userID, id int) (core_domain.RoundSummary, error)
	Answer(ctx context.Context, userID, id int, author string) (engine.AnswerResult, error)
}

type ReviewsHTTPHandler struct {
	service ReviewsService
}

func NewReviewsHTTPHandler(service ReviewsService) *ReviewsHTTPHandler {
	return &ReviewsHTTPHandler{service: service}
}

func (h *ReviewsHTTPHandler) Routes() []core_http_server.Route {
	auth := []core_http_middleware.Middleware{core_http_middleware.RequireAuth()}
	return []core_http_server.Route{
		{
			Method: http.MethodGet, 
			Path: "/playbooks", 
			Handler: h.Playbooks, 
			Middlewares: auth},
		{
			Method: http.MethodPost, 
			Path: "/reviews", 
			Handler: h.Create, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews", 
			Handler: h.List, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}", 
			Handler: h.Get, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/report", 
			Handler: h.Report, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/xlsx", 
			Handler: h.XLSX, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/changes", 
			Handler: h.Changes, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/summary", 
			Handler: h.Summary, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/document", 
			Handler: h.Document, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/docx", 
			Handler: h.DOCX, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/choices", 
			Handler: h.Choices, 
			Middlewares: auth},
		{
			Method: http.MethodPut, 
			Path: "/reviews/{id}/choices/{change}", 
			Handler: h.SaveChoice, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/precedents", 
			Handler: h.Precedents, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/law", 
			Handler: h.LawHints, 
			Middlewares: auth},
		{
			Method: http.MethodGet, 
			Path: "/reviews/{id}/wordings", 
			Handler: h.Wordings, 
			Middlewares: auth},
		{
			Method: http.MethodPost, 
			Path: "/reviews/{id}/answer", 
			Handler: h.Answer, 
			Middlewares: auth},
		{
			Method: http.MethodDelete, 
			Path: "/reviews/{id}", 
			Handler: h.Delete, 
			Middlewares: auth},
	}
}

func identity(r *http.Request, resp *core_http_response.HTTPResponseHandler) (core_auth.Identity, bool) {
	id, ok := core_auth.IdentityFromCtx(r.Context())
	if !ok {
		resp.ErrorResponse(fmt.Errorf("not logged in: %w", core_errors.ErrUnauthorized), "not authenticated")
	}
	return id, ok
}

func pathID(r *http.Request, resp *core_http_response.HTTPResponseHandler) (int, bool) {
	id, err := core_http_request.GetIntPathParam(r, "id")
	if err != nil || id < 1 || id > 2147483647 {
		resp.ErrorResponse(fmt.Errorf("review not found: %w", core_errors.ErrNotFound), "not found")
		return 0, false
	}
	return id, true
}

func (h *ReviewsHTTPHandler) file(rw http.ResponseWriter, r *http.Request, kind string) ([]byte, int, bool) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return nil, 0, false
	}
	id, ok := pathID(r, resp)
	if !ok {
		return nil, 0, false
	}
	data, err := h.service.File(r.Context(), who.UserID, id, kind)
	if err != nil {
		resp.ErrorResponse(err, "failed to get review file")
		return nil, 0, false
	}
	return data, id, true
}

func (h *ReviewsHTTPHandler) json(rw http.ResponseWriter, r *http.Request, kind string) {
	data, _, ok := h.file(rw, r, kind)
	if !ok {
		return
	}
	rw.Header().Set("Content-Type", "application/json; charset=utf-8")
	rw.Header().Set("Cache-Control", "no-store")
	rw.WriteHeader(http.StatusOK)
	_, _ = rw.Write(data)
}
