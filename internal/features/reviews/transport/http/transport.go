package reviews_transport_http

import (
	"context"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"time"

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
		{Method: http.MethodGet, Path: "/playbooks", Handler: h.Playbooks, Middlewares: auth},
		{Method: http.MethodPost, Path: "/reviews", Handler: h.Create, Middlewares: auth},
		{Method: http.MethodGet, Path: "/reviews", Handler: h.List, Middlewares: auth},
		{Method: http.MethodGet, Path: "/reviews/{id}", Handler: h.Get, Middlewares: auth},
		{Method: http.MethodGet, Path: "/reviews/{id}/report", Handler: h.Report, Middlewares: auth},
		{Method: http.MethodGet, Path: "/reviews/{id}/xlsx", Handler: h.XLSX, Middlewares: auth},
		{Method: http.MethodGet, Path: "/reviews/{id}/changes", Handler: h.Changes, Middlewares: auth},
		{Method: http.MethodGet, Path: "/reviews/{id}/document", Handler: h.Document, Middlewares: auth},
		{Method: http.MethodGet, Path: "/reviews/{id}/docx", Handler: h.DOCX, Middlewares: auth},
		{Method: http.MethodGet, Path: "/reviews/{id}/choices", Handler: h.Choices, Middlewares: auth},
		{Method: http.MethodPut, Path: "/reviews/{id}/choices/{change}", Handler: h.SaveChoice, Middlewares: auth},
		{Method: http.MethodPost, Path: "/reviews/{id}/answer", Handler: h.Answer, Middlewares: auth},
		{Method: http.MethodDelete, Path: "/reviews/{id}", Handler: h.Delete, Middlewares: auth},
	}
}

// ---------- DTO ----------

type PlaybookDTO struct {
	Key  string `json:"key"`
	Name string `json:"name"`
	Role string `json:"role"`
}

type ReviewDTO struct {
	ID           int            `json:"id"`
	CreatedAt    time.Time      `json:"created_at"`
	TheirsName   string         `json:"theirs_name"`
	BaseName     string         `json:"base_name"`
	Playbook     string         `json:"playbook"`
	PlaybookName string         `json:"playbook_name"`
	OurRole      string         `json:"our_role"`
	Side         string         `json:"side"`
	Counts       map[string]int `json:"counts"`
	Warnings     []string       `json:"warnings"`
}

// RoleErrorDTO — ответ 422: юрист должен подтвердить роль и отправить договор ещё раз.
type RoleErrorDTO struct {
	Error   string `json:"error"`
	Message string `json:"message"`
	Role    string `json:"role"`
}

func reviewDTO(r core_domain.ContractReview) ReviewDTO {
	if r.Warnings == nil {
		r.Warnings = []string{}
	}
	return ReviewDTO{ID: r.ID, CreatedAt: r.CreatedAt, TheirsName: r.TheirsName, BaseName: r.BaseName, Playbook: r.Playbook,
		PlaybookName: r.PlaybookName, OurRole: r.OurRole, Side: r.Side, Counts: r.Counts, Warnings: r.Warnings}
}

// ---------- обработчики ----------

func identity(r *http.Request, resp *core_http_response.HTTPResponseHandler) (core_auth.Identity, bool) {
	id, ok := core_auth.IdentityFromCtx(r.Context())
	if !ok {
		resp.ErrorResponse(fmt.Errorf("not logged in: %w", core_errors.ErrUnauthorized), "not authenticated")
	}
	return id, ok
}

func (h *ReviewsHTTPHandler) Playbooks(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	pbs, err := h.service.Playbooks(r.Context())
	if err != nil {
		resp.ErrorResponse(err, "failed to list playbooks")
		return
	}
	out := make([]PlaybookDTO, 0, len(pbs))
	for _, p := range pbs {
		out = append(out, PlaybookDTO{Key: p.Key, Name: p.Name, Role: p.Role})
	}
	resp.JSONResponse(http.StatusOK, out)
}

// maxForm — два docx по 30 МБ и поля формы.
const maxForm = 2*core_domain.MaxUploadBytes + (1 << 20)

func readFile(form *multipart.Form, field string) (*core_domain.UploadedFile, error) {
	fhs := form.File[field]
	if len(fhs) == 0 {
		return nil, nil
	}
	fh := fhs[0]
	if fh.Size > core_domain.MaxUploadBytes {
		return nil, fmt.Errorf("файл больше 30 МБ: %w", core_errors.ErrInvalidArgument)
	}
	f, err := fh.Open()
	if err != nil {
		return nil, fmt.Errorf("open upload: %w", err)
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, core_domain.MaxUploadBytes+1))
	if err != nil {
		return nil, fmt.Errorf("read upload: %w", err)
	}
	return &core_domain.UploadedFile{Name: fh.Filename, Data: data}, nil
}

func (h *ReviewsHTTPHandler) Create(rw http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(ctx), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	r.Body = http.MaxBytesReader(rw, r.Body, maxForm)
	if err := r.ParseMultipartForm(8 << 20); err != nil {
		resp.ErrorResponse(fmt.Errorf("форма не разобрана (файлы больше 30 МБ?): %v: %w", err, core_errors.ErrInvalidArgument),
			"invalid upload")
		return
	}
	defer func() { _ = r.MultipartForm.RemoveAll() }()

	theirs, err := readFile(r.MultipartForm, "theirs")
	if err != nil {
		resp.ErrorResponse(err, "invalid upload")
		return
	}
	if theirs == nil {
		resp.ErrorResponse(fmt.Errorf("загрузите версию контрагента: %w", core_errors.ErrInvalidArgument), "invalid upload")
		return
	}
	base, err := readFile(r.MultipartForm, "base")
	if err != nil {
		resp.ErrorResponse(err, "invalid upload")
		return
	}
	req := core_domain.ReviewRequest{
		Theirs: *theirs, Base: base,
		Playbook: r.FormValue("playbook"), OurAuthors: r.FormValue("our_authors"),
		Company: r.FormValue("company"), ConfirmRole: r.FormValue("confirm_role"),
	}
	rev, err := h.service.Create(ctx, who.UserID, req)
	if err != nil {
		var re *engine.RoleError
		if errors.As(err, &re) {
			core_logger.FromCtx(ctx).Warn("review: role not confirmed")
			resp.JSONResponse(http.StatusUnprocessableEntity, RoleErrorDTO{Error: "role_not_confirmed", Message: re.Message, Role: re.Role})
			return
		}
		resp.ErrorResponse(err, "failed to review contract")
		return
	}
	rw.Header().Set("Location", fmt.Sprintf("/api/v1/reviews/%d", rev.ID))
	resp.JSONResponse(http.StatusCreated, reviewDTO(rev))
}

func (h *ReviewsHTTPHandler) List(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	limit, offset, err := core_http_request.GetLimitOffsetQueryParam(r)
	if err != nil {
		resp.ErrorResponse(err, "invalid query")
		return
	}
	l, o := 0, 0
	if limit != nil {
		l = *limit
	}
	if offset != nil {
		o = *offset
	}
	revs, err := h.service.List(r.Context(), who.UserID, l, o)
	if err != nil {
		resp.ErrorResponse(err, "failed to list reviews")
		return
	}
	out := make([]ReviewDTO, 0, len(revs))
	for _, rev := range revs {
		out = append(out, reviewDTO(rev))
	}
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}

func pathID(r *http.Request, resp *core_http_response.HTTPResponseHandler) (int, bool) {
	id, err := core_http_request.GetIntPathParam(r, "id")
	if err != nil || id < 1 || id > 2147483647 {
		resp.ErrorResponse(fmt.Errorf("review not found: %w", core_errors.ErrNotFound), "not found")
		return 0, false
	}
	return id, true
}

func (h *ReviewsHTTPHandler) Get(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	rev, err := h.service.Get(r.Context(), who.UserID, id)
	if err != nil {
		resp.ErrorResponse(err, "failed to get review")
		return
	}
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, reviewDTO(rev))
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

func (h *ReviewsHTTPHandler) Changes(rw http.ResponseWriter, r *http.Request) {
	h.json(rw, r, "changes")
}

// Document — единая версия договора: абзацы с правками для страницы разбора.
func (h *ReviewsHTTPHandler) Document(rw http.ResponseWriter, r *http.Request) {
	h.json(rw, r, "document")
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

func (h *ReviewsHTTPHandler) Delete(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	if err := h.service.Delete(r.Context(), who.UserID, id); err != nil {
		resp.ErrorResponse(err, "failed to delete review")
		return
	}
	resp.StatusCodeResponse(http.StatusNoContent)
}

// ---------- пошаговый просмотр и ответ контрагенту ----------

type ChoiceDTO struct {
	ChangeID string `json:"change_id"`
	Choice   string `json:"choice"`
	Text     string `json:"text"`
}

type SaveChoiceRequest struct {
	Choice string `json:"choice"`
	Text   string `json:"text"`
}

func (r SaveChoiceRequest) Validate() error { return nil } // проверяет core_domain.ReviewChoice в сервисе

type AnswerRequest struct {
	Author string `json:"author"`
}

func (r AnswerRequest) Validate() error { return nil }

func (h *ReviewsHTTPHandler) Choices(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	list, err := h.service.Choices(r.Context(), who.UserID, id)
	if err != nil {
		resp.ErrorResponse(err, "failed to list choices")
		return
	}
	out := make([]ChoiceDTO, 0, len(list))
	for _, c := range list {
		out = append(out, ChoiceDTO{ChangeID: c.ChangeID, Choice: c.Choice, Text: c.Text})
	}
	rw.Header().Set("Cache-Control", "no-store")
	resp.JSONResponse(http.StatusOK, out)
}

func (h *ReviewsHTTPHandler) SaveChoice(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	var req SaveChoiceRequest
	if err := core_http_request.DecodeAndValidateRequest(r, &req); err != nil {
		resp.ErrorResponse(err, "invalid choice")
		return
	}
	c := core_domain.ReviewChoice{ChangeID: r.PathValue("change"), Choice: req.Choice, Text: req.Text}
	if err := h.service.SaveChoice(r.Context(), who.UserID, id, c); err != nil {
		resp.ErrorResponse(err, "failed to save choice")
		return
	}
	resp.StatusCodeResponse(http.StatusNoContent)
}

// Answer отдаёт ответ контрагенту в Word. Файл не сохраняется: собирается по текущим решениям юриста.
func (h *ReviewsHTTPHandler) Answer(rw http.ResponseWriter, r *http.Request) {
	resp := core_http_response.NewHTTPResponseHandler(core_logger.FromCtx(r.Context()), rw)
	who, ok := identity(r, resp)
	if !ok {
		return
	}
	id, ok := pathID(r, resp)
	if !ok {
		return
	}
	var req AnswerRequest
	if err := core_http_request.DecodeAndValidateRequest(r, &req); err != nil {
		resp.ErrorResponse(err, "invalid answer request")
		return
	}
	res, err := h.service.Answer(r.Context(), who.UserID, id, req.Author)
	if err != nil {
		resp.ErrorResponse(err, "failed to build answer")
		return
	}
	name := fmt.Sprintf("Правки_ответ_контрагенту_%d.docx", id)
	rw.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
	rw.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"pravki_answer_%d.docx\"; filename*=UTF-8''%s", id, url.PathEscape(name)))
	rw.Header().Set("Cache-Control", "no-store")
	// счётчики применённых решений; «без отметки» — решения по правкам, которых в рецензировании Word нет
	for k, header := range map[string]string{"accept": "accept", "reject": "reject", "counter": "counter", "без отметки": "untracked"} {
		if v, ok := res.Stats[k]; ok {
			rw.Header().Set("X-Pravki-"+header, fmt.Sprint(v))
		}
	}
	rw.WriteHeader(http.StatusOK)
	_, _ = rw.Write(res.DOCX)
}
