package reviews_transport_http

import (
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"strconv"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_response "github.com/Doomed07/Pravka/internal/core/transport/http/response"
	"github.com/Doomed07/Pravka/internal/engine"
)

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
		Company: r.FormValue("company"), ConfirmRole: r.FormValue("confirm_role"), ProjectName: r.FormValue("project_name"),
	}
	if v := r.FormValue("project_id"); v != "" {
		id, err := strconv.Atoi(v)
		if err != nil || id <= 0 {
			resp.ErrorResponse(fmt.Errorf("номер договора %q: %w", v, core_errors.ErrInvalidArgument), "invalid project")
			return
		}
		req.ProjectID = id
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
	resp.JSONResponse(http.StatusCreated, reviewDTOFromDomain(rev))
}
