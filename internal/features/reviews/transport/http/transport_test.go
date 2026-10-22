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
func (f *fakeService) List(context.Context, int, int, int) ([]core_domain.ContractReview, error) { return nil, nil }
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
	return []byte("<h1>отчёт</h1>"), nil
}
func (f *fakeService) Delete(context.Context, int, int) error { return nil }

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
