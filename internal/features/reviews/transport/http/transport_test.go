package reviews_transport_http

import (
	"bytes"
	"context"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_http_middleware "github.com/Doomed07/Pravka/internal/core/transport/http/middleware"
	core_http_server "github.com/Doomed07/Pravka/internal/core/transport/http/server"
	"github.com/Doomed07/Pravka/internal/engine"
	"go.uber.org/zap"
)

type fakeService struct {
	createErr error
	got       core_domain.ReviewRequest
	userID    int
	choice    core_domain.ReviewChoice
	author    string
}

func (f *fakeService) Playbooks(context.Context) ([]core_domain.Playbook, error) {
	return []core_domain.Playbook{{Key: "a.yaml", Name: "A", Role: "Заказчик"}}, nil
}
func (f *fakeService) Create(_ context.Context, userID int, r core_domain.ReviewRequest) (core_domain.ContractReview, error) {
	f.got, f.userID = r, userID
	if f.createErr != nil {
		return core_domain.ContractReview{}, f.createErr
	}
	return core_domain.ContractReview{ID: 5, UserID: userID, TheirsName: r.Theirs.Name, Counts: map[string]int{"всего": 1}}, nil
}
func (f *fakeService) List(context.Context, int, int, int) ([]core_domain.ContractReview, error) {
	return nil, nil
}
func (f *fakeService) Get(_ context.Context, userID, id int) (core_domain.ContractReview, error) {
	if userID != 1 {
		return core_domain.ContractReview{}, core_errors.ErrNotFound
	}
	return core_domain.ContractReview{ID: id}, nil
}
func (f *fakeService) File(_ context.Context, userID, id int, kind string) ([]byte, error) {
	if userID != 1 {
		return nil, core_errors.ErrNotFound
	}
	switch kind {
	case "document":
		return []byte(`[{"index":0}]`), nil
	case "docx":
		if id == 4 { // разбор, сделанный до появления единой версии
			return nil, core_errors.ErrNotFound
		}
		return []byte("PKdocx"), nil
	}
	return []byte("<h1>отчёт</h1>"), nil
}
func (f *fakeService) Delete(context.Context, int, int) error { return nil }
func (f *fakeService) Choices(_ context.Context, userID, _ int) ([]core_domain.ReviewChoice, error) {
	if userID != 1 {
		return nil, core_errors.ErrNotFound
	}
	return []core_domain.ReviewChoice{{ChangeID: "E001", Choice: "counter", Text: "30 дней"}}, nil
}
func (f *fakeService) SaveChoice(_ context.Context, userID, _ int, c core_domain.ReviewChoice) error {
	if userID != 1 {
		return core_errors.ErrNotFound
	}
	if c.Choice == "maybe" {
		return core_errors.ErrInvalidArgument
	}
	f.choice = c
	return nil
}
func (f *fakeService) Precedents(_ context.Context, userID, _ int) ([]core_domain.Precedent, error) {
	if userID != 1 {
		return nil, core_errors.ErrNotFound
	}
	return []core_domain.Precedent{{ChangeID: "E002", ReviewID: 3, TheirsName: "Поставка_v2.docx", Choice: "counter",
		Text: "15 дней", Same: true, Score: 0.8}}, nil
}
func (f *fakeService) LawHints(_ context.Context, userID, _ int) ([]core_domain.LawHint, error) {
	if userID != 1 {
		return nil, core_errors.ErrNotFound
	}
	return []core_domain.LawHint{{ChangeID: "E002", Article: "511", Point: "3", Title: "Восполнение недопоставки товаров",
		Text: "3. Покупатель вправе…", Distance: 0.21}}, nil
}
func (f *fakeService) Answer(_ context.Context, userID, _ int, author string) (engine.AnswerResult, error) {
	if userID != 1 {
		return engine.AnswerResult{}, core_errors.ErrNotFound
	}
	f.author = author
	return engine.AnswerResult{DOCX: []byte("PKanswer"), Stats: map[string]int{"reject": 2, "без отметки": 1}}, nil
}

// router собирает маршруты так же, как main: с проверкой происхождения запроса и логгером в контексте.
func router(svc ReviewsService, userID int) http.Handler {
	r := core_http_server.NewAPIVersionRouter(core_http_server.ApiVersion1, core_http_middleware.SameOrigin())
	r.RegisterRoutes(NewReviewsHTTPHandler(svc).Routes()...)
	h := r.WithMiddleware()
	log := &core_logger.Logger{Logger: zap.NewNop()}
	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		ctx := core_logger.ToCtx(req.Context(), log)
		if userID > 0 {
			ctx = core_auth.WithIdentity(ctx, core_auth.Identity{UserID: userID, Username: "u"})
		}
		h.ServeHTTP(w, req.WithContext(ctx))
	})
}

func upload(t *testing.T, fields map[string]string, marker bool) *http.Request {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, _ := mw.CreateFormFile("theirs", "Договор.docx")
	_, _ = fw.Write([]byte("PK\x03\x04"))
	for k, v := range fields {
		_ = mw.WriteField(k, v)
	}
	_ = mw.Close()
	req := httptest.NewRequest(http.MethodPost, "/reviews", &buf)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	if marker {
		req.Header.Set("X-Requested-With", core_http_middleware.UploadMarker)
	}
	return req
}

func TestCreate(t *testing.T) {
	svc := &fakeService{}
	rec := httptest.NewRecorder()
	router(svc, 1).ServeHTTP(rec, upload(t, map[string]string{"playbook": "a.yaml", "confirm_role": "Заказчик"}, true))
	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d; body = %s", rec.Code, rec.Body.String())
	}
	if svc.userID != 1 || svc.got.Theirs.Name != "Договор.docx" || svc.got.Playbook != "a.yaml" || svc.got.ConfirmRole != "Заказчик" {
		t.Errorf("service got %+v (user %d)", svc.got, svc.userID)
	}
}

func TestCreate_Guards(t *testing.T) {
	cases := []struct {
		name   string
		user   int
		marker bool
		err    error
		want   int
	}{
		{"guest", 0, true, nil, http.StatusUnauthorized},
		{"upload without marker (possible cross-site form)", 1, false, nil, http.StatusBadRequest},
		{"role not confirmed", 1, true, &engine.RoleError{Message: "нужно подтвердить", Role: "Заказчик"}, http.StatusUnprocessableEntity},
		{"engine down", 1, true, core_errors.ErrUnavailable, http.StatusBadGateway},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			router(&fakeService{createErr: c.err}, c.user).ServeHTTP(rec, upload(t, nil, c.marker))
			if rec.Code != c.want {
				t.Fatalf("status = %d, want %d; body = %s", rec.Code, c.want, rec.Body.String())
			}
			if c.want == http.StatusUnprocessableEntity {
				var body RoleErrorDTO
				_ = json.Unmarshal(rec.Body.Bytes(), &body)
				if body.Role != "Заказчик" || body.Error != "role_not_confirmed" {
					t.Errorf("body = %+v", body)
				}
			}
		})
	}
}

func TestReport_CSPAndOwnership(t *testing.T) {
	rec := httptest.NewRecorder()
	router(&fakeService{}, 1).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/reviews/5/report", nil))
	if rec.Code != http.StatusOK || !strings.Contains(rec.Header().Get("Content-Security-Policy"), "default-src 'none'") {
		t.Fatalf("status = %d, csp = %q", rec.Code, rec.Header().Get("Content-Security-Policy"))
	}
	rec = httptest.NewRecorder()
	router(&fakeService{}, 2).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/reviews/5/report", nil))
	if rec.Code != http.StatusNotFound {
		t.Fatalf("someone else's report: status = %d, want 404", rec.Code)
	}
	rec = httptest.NewRecorder()
	router(&fakeService{}, 1).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/reviews/abc", nil))
	if rec.Code != http.StatusNotFound {
		t.Fatalf("bad id: status = %d, want 404", rec.Code)
	}
}

func TestUnifiedVersion(t *testing.T) {
	get := func(userID int, path string) *httptest.ResponseRecorder {
		rec := httptest.NewRecorder()
		router(&fakeService{}, userID).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		return rec
	}
	if rec := get(1, "/reviews/5/document"); rec.Code != http.StatusOK || rec.Body.String() != `[{"index":0}]` ||
		!strings.HasPrefix(rec.Header().Get("Content-Type"), "application/json") {
		t.Fatalf("document: status = %d, body = %q", rec.Code, rec.Body.String())
	}
	rec := get(1, "/reviews/5/docx")
	if rec.Code != http.StatusOK || rec.Body.String() != "PKdocx" ||
		!strings.Contains(rec.Header().Get("Content-Disposition"), "pravki_5.docx") {
		t.Fatalf("docx: status = %d, disposition = %q", rec.Code, rec.Header().Get("Content-Disposition"))
	}
	for _, path := range []string{"/reviews/5/document", "/reviews/5/docx"} {
		if rec := get(2, path); rec.Code != http.StatusNotFound {
			t.Errorf("someone else's %s: status = %d, want 404", path, rec.Code)
		}
	}
	if rec := get(1, "/reviews/4/docx"); rec.Code != http.StatusNotFound {
		t.Errorf("old review without docx: status = %d, want 404", rec.Code)
	}
}

func TestChoicesAndAnswer(t *testing.T) {
	svc := &fakeService{}
	do := func(userID int, method, path, body string) *httptest.ResponseRecorder {
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router(svc, userID).ServeHTTP(rec, req)
		return rec
	}
	if rec := do(1, http.MethodGet, "/reviews/5/choices", ""); rec.Code != http.StatusOK ||
		!strings.Contains(rec.Body.String(), `"change_id":"E001"`) || !strings.Contains(rec.Body.String(), `"text":"30 дней"`) {
		t.Fatalf("choices: %d %s", rec.Code, rec.Body.String())
	}
	if rec := do(1, http.MethodPut, "/reviews/5/choices/E007", `{"choice":"counter","text":"45 дней"}`); rec.Code != http.StatusNoContent ||
		svc.choice != (core_domain.ReviewChoice{ChangeID: "E007", Choice: "counter", Text: "45 дней"}) {
		t.Fatalf("save: %d, %+v", rec.Code, svc.choice)
	}
	if rec := do(1, http.MethodPut, "/reviews/5/choices/E007", `не json`); rec.Code != http.StatusBadRequest {
		t.Fatalf("bad json: %d", rec.Code)
	}
	if rec := do(1, http.MethodPut, "/reviews/5/choices/E007", `{"choice":"maybe"}`); rec.Code != http.StatusBadRequest {
		t.Fatalf("bad choice: %d", rec.Code)
	}
	if rec := do(1, http.MethodGet, "/reviews/5/precedents", ""); rec.Code != http.StatusOK ||
		!strings.Contains(rec.Body.String(), `"change_id":"E002"`) || !strings.Contains(rec.Body.String(), `"text":"15 дней"`) ||
		!strings.Contains(rec.Body.String(), `"same":true`) {
		t.Fatalf("precedents: %d %s", rec.Code, rec.Body.String())
	}
	if rec := do(1, http.MethodGet, "/reviews/5/law", ""); rec.Code != http.StatusOK ||
		!strings.Contains(rec.Body.String(), `"article":"511"`) || !strings.Contains(rec.Body.String(), `"point":"3"`) {
		t.Fatalf("law: %d %s", rec.Code, rec.Body.String())
	}
	rec := do(1, http.MethodPost, "/reviews/5/answer", `{"author":"Иванова А."}`)
	if rec.Code != http.StatusOK || rec.Body.String() != "PKanswer" || svc.author != "Иванова А." ||
		!strings.Contains(rec.Header().Get("Content-Disposition"), "pravki_answer_5.docx") || rec.Header().Get("X-Pravki-reject") != "2" ||
		rec.Header().Get("X-Pravki-untracked") != "1" {
		t.Fatalf("answer: %d %q %v", rec.Code, svc.author, rec.Header())
	}
	for _, c := range []struct{ method, path, body string }{
		{http.MethodGet, "/reviews/5/choices", ""},
		{http.MethodPut, "/reviews/5/choices/E007", `{"choice":"accept"}`},
		{http.MethodPost, "/reviews/5/answer", `{}`},
		{http.MethodGet, "/reviews/5/precedents", ""},
		{http.MethodGet, "/reviews/5/law", ""},
	} {
		if rec := do(2, c.method, c.path, c.body); rec.Code != http.StatusNotFound {
			t.Errorf("someone else's %s %s: %d, want 404", c.method, c.path, rec.Code)
		}
	}
}
