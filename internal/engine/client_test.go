package engine

import (
	"context"
	"encoding/base64"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func fakeEngine(t *testing.T, status int, body string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Engine-Token") != "tok" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		if r.URL.Path == "/review" {
			if err := r.ParseMultipartForm(1 << 20); err != nil {
				t.Errorf("engine got bad form: %v", err)
			}
			f, fh, err := r.FormFile("theirs")
			if err != nil {
				t.Errorf("no theirs: %v", err)
			} else {
				data, _ := io.ReadAll(f)
				if string(data) != "PKdocx" || fh.Filename != "theirs.docx" { // настоящее имя файла движку не уходит
					t.Errorf("theirs = %q %q", fh.Filename, data)
				}
			}
			if r.FormValue("playbook") != "services_example.yaml" {
				t.Errorf("playbook = %q", r.FormValue("playbook"))
			}
		}
		w.WriteHeader(status)
		_, _ = io.WriteString(w, body)
	}))
}

func client(url string) *Client {
	return NewClient(Config{URL: url, Token: "tok", Timeout: 5 * time.Second})
}

var req = core_domain.ReviewRequest{Theirs: core_domain.UploadedFile{Name: "Секретный договор.docx", Data: []byte("PKdocx")},
	Playbook: "services_example.yaml"}

func TestReview_OK(t *testing.T) {
	x := base64.StdEncoding.EncodeToString([]byte("PKxlsx"))
	d := base64.StdEncoding.EncodeToString([]byte("PKdocx"))
	srv := fakeEngine(t, 200, `{"counts":{"всего":2},"warnings":[],"report_html":"<p>r</p>","report_xlsx":"`+x+
		`","changes":[],"document":[{"index":0}],"unified_docx":"`+d+`"}`)
	defer srv.Close()
	res, xlsx, err := client(srv.URL).Review(context.Background(), req)
	if err != nil || res.Counts["всего"] != 2 || string(xlsx) != "PKxlsx" || res.ReportHTML != "<p>r</p>" {
		t.Fatalf("res=%+v xlsx=%q err=%v", res, xlsx, err)
	}
	if string(res.Unified) != "PKdocx" || string(res.Document) != `[{"index":0}]` || res.UnifiedDOCX != "" {
		t.Fatalf("unified=%q document=%s", res.Unified, res.Document)
	}
}

func TestReview_Errors(t *testing.T) {
	cases := []struct {
		status int
		body   string
		check  func(error) bool
	}{
		{422, `{"error":"role_not_confirmed","message":"не подтверждена","role":"Заказчик"}`, func(err error) bool {
			var re *RoleError
			return errors.As(err, &re) && re.Role == "Заказчик" && errors.Is(err, core_errors.ErrUnprocessable)
		}},
		{400, `{"error":"bad_file","message":"не docx"}`, func(err error) bool {
			return errors.Is(err, core_errors.ErrInvalidArgument) && strings.Contains(err.Error(), "не docx")
		}},
		{500, `{"error":"internal"}`, func(err error) bool { return errors.Is(err, core_errors.ErrUnavailable) }},
	}
	for _, c := range cases {
		srv := fakeEngine(t, c.status, c.body)
		_, _, err := client(srv.URL).Review(context.Background(), req)
		srv.Close()
		if !c.check(err) {
			t.Errorf("status %d: unexpected err %v", c.status, err)
		}
	}
}

func TestEngineDown(t *testing.T) {
	_, _, err := client("http://127.0.0.1:1").Review(context.Background(), req)
	if !errors.Is(err, core_errors.ErrUnavailable) {
		t.Fatalf("err = %v", err)
	}
}

func TestAnswer_SendsFormAndDecodesFile(t *testing.T) {
	d := base64.StdEncoding.EncodeToString([]byte("PKanswer"))
	var got map[string]string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/answer" || r.Header.Get("X-Engine-Token") != "tok" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		if err := r.ParseMultipartForm(1 << 20); err != nil {
			t.Errorf("bad form: %v", err)
		}
		f, _, err := r.FormFile("unified")
		if err != nil {
			t.Errorf("no unified: %v", err)
			return
		}
		data, _ := io.ReadAll(f)
		got = map[string]string{"unified": string(data), "changes": r.FormValue("changes"), "choices": r.FormValue("choices"),
			"author": r.FormValue("author"), "document": r.FormValue("document")}
		_, _ = w.Write([]byte(`{"answer_docx":"` + d + `","stats":{"reject":1}}`))
	}))
	defer srv.Close()
	res, err := client(srv.URL).Answer(context.Background(), []byte("PKunified"), []byte(`[{"index":0}]`), []byte(`[{"id":"E001"}]`),
		[]core_domain.ReviewChoice{{ChangeID: "E001", Choice: "counter", Text: "30 дней"}}, "Иванова А.")
	if err != nil || string(res.DOCX) != "PKanswer" || res.Stats["reject"] != 1 {
		t.Fatalf("res = %+v, err = %v", res, err)
	}
	if got["unified"] != "PKunified" || got["changes"] != `[{"id":"E001"}]` || got["author"] != "Иванова А." ||
		got["document"] != `[{"index":0}]` ||
		got["choices"] != `{"E001":{"choice":"counter","text":"30 дней"}}` {
		t.Fatalf("engine got %+v", got)
	}
}

func TestFirstVersionFieldAndParties(t *testing.T) {
	var gotFirst, gotCompany string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseMultipartForm(1 << 20)
		switch r.URL.Path {
		case "/review":
			gotFirst = r.FormValue("first_version")
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"counts":{},"unified_docx":"","report_xlsx":""}`))
		case "/parties":
			gotCompany = r.FormValue("company")
			_, _ = w.Write([]byte(`{"parties":[{"role":"Исполнитель","name":"Альфа","inn":"7701234567"},{"role":"Заказчик","name":"Бета","inn":""}],
				"counterparty":{"role":"Заказчик","name":"Бета","inn":""},"ours":{"role":"Исполнитель","name":"Альфа","inn":"7701234567"},
				"title":"Договор оказания услуг № 1","contract_type":"services","playbook":"services_example.yaml","source":"model"}`))
		}
	}))
	defer srv.Close()
	c := NewClient(Config{URL: srv.URL, Timeout: time.Second})
	file := core_domain.UploadedFile{Name: "a.docx", Data: []byte("PKdocx")}
	if _, _, err := c.Review(context.Background(), core_domain.ReviewRequest{Theirs: file, FirstVersion: true}); err != nil || gotFirst != "1" {
		t.Fatalf("first_version = %q, err %v", gotFirst, err)
	}
	if _, _, err := c.Review(context.Background(), core_domain.ReviewRequest{Theirs: file}); err != nil || gotFirst != "" {
		t.Fatalf("без признака first_version = %q, err %v", gotFirst, err)
	}
	got, err := c.Parties(context.Background(), file, "7701234567")
	if err != nil || gotCompany != "7701234567" {
		t.Fatalf("parties: %v (company %q)", err, gotCompany)
	}
	if got.Counterparty == nil || got.Counterparty.Name != "Бета" || got.Ours == nil || got.Ours.INN != "7701234567" ||
		got.Title != "Договор оказания услуг № 1" || got.ContractType != "services" || got.Playbook != "services_example.yaml" || got.Source != "model" {
		t.Errorf("parties = %+v", got)
	}
}
