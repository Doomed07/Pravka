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
	renamed   string
	moved     [2]int
	company   string
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
	return core_domain.ContractReview{ID: id, HasDocx: id != 7}, nil // разбор 7 — файл контрагента не .docx: Word нет
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
func (f *fakeService) Wordings(_ context.Context, userID, _ int) ([]core_domain.Wording, error) {
	if userID != 1 {
		return nil, core_errors.ErrNotFound
	}
	return []core_domain.Wording{{ChangeID: "E002", ReviewID: 9, TheirsName: "Поставка_2025.docx", Clause: "3.1",
		Text: "Поставщик поставляет Товар в течение 20 дней."}}, nil
}
func (f *fakeService) Summary(_ context.Context, userID, _ int) (core_domain.RoundSummary, error) {
	if userID != 1 {
		return core_domain.RoundSummary{}, core_errors.ErrNotFound
	}
	return core_domain.RoundSummary{Technical: 2, Topics: []core_domain.RoundTopic{{Topic: "порядок и сроки оплаты",
		Verdicts: map[string]int{core_domain.VerdictReject: 1}, Silent: 1, Items: []core_domain.RoundItem{{ChangeID: "E003",
			Clause: "2.3", Kind: "replace", Verdict: core_domain.VerdictReject, Silent: true, Before: "10 дней", After: "30 дней"}}}}}, nil
}
func (f *fakeService) Projects(_ context.Context, userID int) ([]core_domain.ProjectSummary, error) {
	if userID != 1 {
		return []core_domain.ProjectSummary{}, nil
	}
	return []core_domain.ProjectSummary{{Project: core_domain.Project{ID: 3, Name: "Поставка Омега"}, Rounds: 2, LastReviewID: 9,
		Playbook: "supply.yaml", OurRole: "Поставщик", ContractType: "supply"}}, nil
}
func (f *fakeService) Project(_ context.Context, userID, id int) (core_domain.ProjectView, error) {
	if userID != 1 || id != 3 {
		return core_domain.ProjectView{}, core_errors.ErrNotFound
	}
	return core_domain.ProjectView{Project: core_domain.ProjectSummary{Project: core_domain.Project{ID: 3, Name: "Поставка Омега"}, Rounds: 2},
		Rounds: []core_domain.ProjectRoundView{{ReviewID: 8, Round: 1, TheirsName: "v1.docx", Total: 4, New: 4},
			{ReviewID: 9, Round: 2, TheirsName: "v2.docx", Total: 5, New: 1, Repeat: 2, Returned: 1, Closed: 3}}}, nil
}
func (f *fakeService) Counterparties(_ context.Context, userID int) ([]core_domain.CounterpartySummary, error) {
	if userID != 1 {
		return []core_domain.CounterpartySummary{}, nil
	}
	return []core_domain.CounterpartySummary{{Counterparty: core_domain.Counterparty{ID: 2, Name: "ООО «Ромашка»", INN: "7702345678", Dir: "ООО «Ромашка»"},
		Contracts: 1, Rounds: 2}}, nil
}
func (f *fakeService) Counterparty(_ context.Context, userID, id int) (core_domain.CounterpartyView, error) {
	if userID != 1 || id != 2 {
		return core_domain.CounterpartyView{}, core_errors.ErrNotFound
	}
	return core_domain.CounterpartyView{
		Counterparty: core_domain.CounterpartySummary{Counterparty: core_domain.Counterparty{ID: 2, Name: "ООО «Ромашка»"}, Contracts: 1},
		Projects: []core_domain.ProjectSummary{{Project: core_domain.Project{ID: 3, Name: "Поставка", CounterpartyID: 2,
			CounterpartyName: "ООО «Ромашка»", Dir: "ООО «Ромашка»/Поставка"}, Rounds: 2}}}, nil
}
func (f *fakeService) RenameCounterparty(_ context.Context, userID, id int, name, inn string) error {
	if userID != 1 || id != 2 {
		return core_errors.ErrNotFound
	}
	f.renamed = name + "|" + inn
	return nil
}
func (f *fakeService) MoveProject(_ context.Context, userID, projectID, counterpartyID int) error {
	if userID != 1 {
		return core_errors.ErrNotFound
	}
	f.moved = [2]int{projectID, counterpartyID}
	return nil
}
func (f *fakeService) DetectParties(_ context.Context, theirs core_domain.UploadedFile, company string) (core_domain.DetectedParties, error) {
	f.company = company
	return core_domain.DetectedParties{
		Parties:      []core_domain.DetectedParty{{Role: "Исполнитель", Name: "Альфа"}, {Role: "Заказчик", Name: "Бета", INN: "7702345678"}},
		Counterparty: &core_domain.DetectedParty{Role: "Заказчик", Name: "Бета", INN: "7702345678"}}, nil
}
func (f *fakeService) Rounds(_ context.Context, userID, _ int) (core_domain.ReviewRounds, error) {
	if userID != 1 {
		return core_domain.ReviewRounds{}, core_errors.ErrNotFound
	}
	return core_domain.ReviewRounds{Project: core_domain.ProjectSummary{Project: core_domain.Project{ID: 3, Name: "Поставка Омега"}, Rounds: 2},
		Round: 2, PrevReviewID: 8, Comparison: core_domain.RoundComparison{
			Links: []core_domain.RoundLink{{ChangeID: "E001", Relation: core_domain.RelationRepeat, Round: 1, ReviewID: 8,
				PastChangeID: "E004", PastBefore: "30%", PastAfter: "10%", Decision: core_domain.ChoiceReject},
				{ChangeID: "E002", Relation: core_domain.RelationNew}},
			Closed: []core_domain.RoundClosed{{Round: 1, ReviewID: 8, ChangeID: "E007", Clause: "5.1", Decision: core_domain.ChoiceCounter,
				DecisionText: "0,05%"}}}}, nil
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
	if rec := do(1, http.MethodGet, "/reviews/5/wordings", ""); rec.Code != http.StatusOK ||
		!strings.Contains(rec.Body.String(), `"review_id":9`) || !strings.Contains(rec.Body.String(), `"clause":"3.1"`) {
		t.Fatalf("wordings: %d %s", rec.Code, rec.Body.String())
	}
	if rec := do(1, http.MethodGet, "/reviews/5/summary", ""); rec.Code != http.StatusOK ||
		!strings.Contains(rec.Body.String(), `"technical":2`) || !strings.Contains(rec.Body.String(), `"verdicts":{"reject":1}`) ||
		!strings.Contains(rec.Body.String(), `"change_id":"E003"`) || !strings.Contains(rec.Body.String(), `"silent":true`) {
		t.Fatalf("summary: %d %s", rec.Code, rec.Body.String())
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
		{http.MethodGet, "/reviews/5/wordings", ""},
		{http.MethodGet, "/reviews/5/summary", ""},
	} {
		if rec := do(2, c.method, c.path, c.body); rec.Code != http.StatusNotFound {
			t.Errorf("someone else's %s %s: %d, want 404", c.method, c.path, rec.Code)
		}
	}
}

func TestProjectsAndRounds(t *testing.T) {
	get := func(userID int, path string) *httptest.ResponseRecorder {
		rec := httptest.NewRecorder()
		router(&fakeService{}, userID).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		return rec
	}
	if rec := get(1, "/projects"); rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"name":"Поставка Омега"`) ||
		!strings.Contains(rec.Body.String(), `"rounds":2`) || !strings.Contains(rec.Body.String(), `"our_role":"Поставщик"`) ||
		!strings.Contains(rec.Body.String(), `"last_review_id":9`) {
		t.Fatalf("projects: %d %s", rec.Code, rec.Body.String())
	}
	if rec := get(2, "/projects"); rec.Code != http.StatusOK || strings.TrimSpace(rec.Body.String()) != "[]" {
		t.Errorf("projects of a user without any: %d %s", rec.Code, rec.Body.String())
	}
	if rec := get(1, "/projects/3"); rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"review_id":9`) ||
		!strings.Contains(rec.Body.String(), `"returned":1`) || !strings.Contains(rec.Body.String(), `"closed":3`) {
		t.Fatalf("project: %d %s", rec.Code, rec.Body.String())
	}
	if rec := get(1, "/reviews/9/rounds"); rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"relation":"repeat"`) ||
		!strings.Contains(rec.Body.String(), `"past_change_id":"E004"`) || !strings.Contains(rec.Body.String(), `"decision":"reject"`) ||
		!strings.Contains(rec.Body.String(), `"prev_review_id":8`) || !strings.Contains(rec.Body.String(), `"decision_text":"0,05%"`) {
		t.Fatalf("rounds: %d %s", rec.Code, rec.Body.String())
	}
	for _, c := range []struct {
		user int
		path string
		want int
	}{
		{0, "/projects", http.StatusUnauthorized}, {0, "/projects/3", http.StatusUnauthorized}, {0, "/reviews/9/rounds", http.StatusUnauthorized},
		{2, "/projects/3", http.StatusNotFound}, {1, "/projects/4", http.StatusNotFound}, {2, "/reviews/9/rounds", http.StatusNotFound},
		{1, "/projects/abc", http.StatusNotFound},
	} {
		if rec := get(c.user, c.path); rec.Code != c.want {
			t.Errorf("user %d GET %s: %d, want %d", c.user, c.path, rec.Code, c.want)
		}
	}
}

func TestCreate_ProjectFields(t *testing.T) {
	svc := &fakeService{}
	rec := httptest.NewRecorder()
	router(svc, 1).ServeHTTP(rec, upload(t, map[string]string{"project_id": "3"}, true))
	if rec.Code != http.StatusCreated || svc.got.ProjectID != 3 || svc.got.ProjectName != "" {
		t.Fatalf("очередной раунд: status = %d, got %+v", rec.Code, svc.got)
	}
	rec = httptest.NewRecorder()
	router(svc, 1).ServeHTTP(rec, upload(t, map[string]string{"project_name": "Поставка Омега"}, true))
	if rec.Code != http.StatusCreated || svc.got.ProjectID != 0 || svc.got.ProjectName != "Поставка Омега" {
		t.Fatalf("новый договор: status = %d, got %+v", rec.Code, svc.got)
	}
	for _, bad := range []string{"abc", "0", "-2", "3.5"} {
		rec = httptest.NewRecorder()
		router(svc, 1).ServeHTTP(rec, upload(t, map[string]string{"project_id": bad}, true))
		if rec.Code != http.StatusBadRequest {
			t.Errorf("project_id %q: status = %d, want 400", bad, rec.Code)
		}
	}
}

func TestGet_HasDocxTellsWhetherWordFileExists(t *testing.T) {
	get := func(path string) string {
		rec := httptest.NewRecorder()
		router(&fakeService{}, 1).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		return rec.Body.String()
	}
	if body := get("/reviews/5"); !strings.Contains(body, `"has_docx":true`) {
		t.Errorf("разбор docx: %s", body)
	}
	if body := get("/reviews/7"); !strings.Contains(body, `"has_docx":false`) {
		t.Errorf("разбор PDF или odt: %s", body)
	}
}

func TestCreate_CounterpartyFields(t *testing.T) {
	svc := &fakeService{}
	rec := httptest.NewRecorder()
	router(svc, 1).ServeHTTP(rec, upload(t, map[string]string{"counterparty_id": "2"}, true))
	if rec.Code != http.StatusCreated || svc.got.CounterpartyID != 2 {
		t.Fatalf("существующий контрагент: status = %d, got %+v", rec.Code, svc.got)
	}
	rec = httptest.NewRecorder()
	router(svc, 1).ServeHTTP(rec, upload(t, map[string]string{"counterparty_name": "ООО «Ромашка»", "counterparty_inn": "7702345678"}, true))
	if rec.Code != http.StatusCreated || svc.got.CounterpartyName != "ООО «Ромашка»" || svc.got.CounterpartyINN != "7702345678" {
		t.Fatalf("новый контрагент: status = %d, got %+v", rec.Code, svc.got)
	}
	for _, bad := range []string{"abc", "0", "-1"} {
		rec = httptest.NewRecorder()
		router(svc, 1).ServeHTTP(rec, upload(t, map[string]string{"counterparty_id": bad}, true))
		if rec.Code != http.StatusBadRequest {
			t.Errorf("counterparty_id %q: status = %d, want 400", bad, rec.Code)
		}
	}
}

func TestCreate_FirstVersionField(t *testing.T) {
	svc := &fakeService{}
	router(svc, 1).ServeHTTP(httptest.NewRecorder(), upload(t, map[string]string{"first_version": "1"}, true))
	if !svc.got.FirstVersion {
		t.Errorf("first_version=1 не дошёл до сервиса: %+v", svc.got)
	}
	router(svc, 1).ServeHTTP(httptest.NewRecorder(), upload(t, map[string]string{"first_version": "yes"}, true))
	if svc.got.FirstVersion {
		t.Errorf("только «1» включает первую версию: %+v", svc.got)
	}
}

func TestCounterparties(t *testing.T) {
	get := func(user int, path string) (int, string) {
		rec := httptest.NewRecorder()
		router(&fakeService{}, user).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		return rec.Code, rec.Body.String()
	}
	if code, body := get(1, "/counterparties"); code != http.StatusOK || !strings.Contains(body, `"name":"ООО «Ромашка»"`) ||
		!strings.Contains(body, `"contracts":1`) || !strings.Contains(body, `"has_folder":true`) {
		t.Errorf("список: %d %s", code, body)
	}
	if code, body := get(1, "/counterparties/2"); code != http.StatusOK || !strings.Contains(body, `"projects":[{"id":3`) ||
		!strings.Contains(body, `"counterparty_name":"ООО «Ромашка»"`) {
		t.Errorf("страница контрагента: %d %s", code, body)
	}
	if code, _ := get(2, "/counterparties/2"); code != http.StatusNotFound {
		t.Errorf("чужой контрагент: %d, want 404", code)
	}
	if code, _ := get(0, "/counterparties"); code != http.StatusUnauthorized {
		t.Errorf("гость: %d, want 401", code)
	}
}

func TestUpdateCounterpartyAndMoveProject(t *testing.T) {
	svc := &fakeService{}
	send := func(method, path, body string) int {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		router(svc, 1).ServeHTTP(rec, req)
		return rec.Code
	}
	if code := send(http.MethodPatch, "/counterparties/2", `{"name":"ООО «Новая»","inn":"7702345678"}`); code != http.StatusNoContent ||
		svc.renamed != "ООО «Новая»|7702345678" {
		t.Errorf("переименование: %d, %q", code, svc.renamed)
	}
	if code := send(http.MethodPatch, "/counterparties/99", `{"name":"x"}`); code != http.StatusNotFound {
		t.Errorf("чужой контрагент: %d", code)
	}
	if code := send(http.MethodPatch, "/projects/3", `{"counterparty_id":2}`); code != http.StatusNoContent || svc.moved != [2]int{3, 2} {
		t.Errorf("перенос договора: %d, %v", code, svc.moved)
	}
}

func TestDetectParties(t *testing.T) {
	svc := &fakeService{}
	req := upload(t, map[string]string{"company": "7701234567"}, true)
	req.URL.Path = "/contracts/detect"
	rec := httptest.NewRecorder()
	router(svc, 1).ServeHTTP(rec, req)
	body := rec.Body.String()
	if rec.Code != http.StatusOK || svc.company != "7701234567" || !strings.Contains(body, `"counterparty":{"role":"Заказчик","name":"Бета","inn":"7702345678"}`) ||
		!strings.Contains(body, `"parties":[{"role":"Исполнитель","name":"Альфа","inn":""}`) {
		t.Fatalf("status = %d; body = %s", rec.Code, body)
	}
	req = upload(t, nil, false) // без отметки загрузки: возможная междоменная форма
	req.URL.Path = "/contracts/detect"
	rec = httptest.NewRecorder()
	router(svc, 1).ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("без отметки: %d, want 400", rec.Code)
	}
}
