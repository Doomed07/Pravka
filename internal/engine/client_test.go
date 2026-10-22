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
