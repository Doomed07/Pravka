package core_http_middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

const jsonType = "application/json"

func TestSameOrigin(t *testing.T) {
	tests := []struct {
		name       string
		method     string
		header     map[string]string
		wantStatus int
	}{
		// безопасные методы данных не меняют: проверки к ним не применяются
		{name: "GET from a foreign origin", method: http.MethodGet, header: map[string]string{"Origin": "http://evil.example"}, wantStatus: http.StatusOK},
		{name: "GET cross-site", method: http.MethodGet, header: map[string]string{"Sec-Fetch-Site": "cross-site"}, wantStatus: http.StatusOK},
		{name: "HEAD from a foreign origin", method: http.MethodHead, header: map[string]string{"Origin": "http://evil.example"}, wantStatus: http.StatusOK},
		{name: "OPTIONS from a foreign origin", method: http.MethodOptions, header: map[string]string{"Origin": "http://evil.example"}, wantStatus: http.StatusOK},

		// Origin
		{name: "POST without Origin (curl)", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType}, wantStatus: http.StatusOK},
		{name: "POST from our own origin", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType, "Origin": "http://localhost:8080"}, wantStatus: http.StatusOK},
		{name: "POST from a foreign origin", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType, "Origin": "http://evil.example"}, wantStatus: http.StatusForbidden},
		{name: "POST from another port", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType, "Origin": "http://localhost:9999"}, wantStatus: http.StatusForbidden},
		{name: "POST from origin null", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType, "Origin": "null"}, wantStatus: http.StatusForbidden},
		{name: "POST with a malformed origin", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType, "Origin": "://bad"}, wantStatus: http.StatusForbidden},
		{name: "DELETE from a foreign origin", method: http.MethodDelete, header: map[string]string{"Origin": "http://evil.example"}, wantStatus: http.StatusForbidden},

		// Sec-Fetch-Site
		{name: "POST same-origin", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType, "Sec-Fetch-Site": "same-origin"}, wantStatus: http.StatusOK},
		{name: "POST typed in the address bar (none)", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType, "Sec-Fetch-Site": "none"}, wantStatus: http.StatusOK},
		{name: "POST cross-site", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType, "Sec-Fetch-Site": "cross-site"}, wantStatus: http.StatusForbidden},
		{name: "POST same-site (a sibling domain)", method: http.MethodPost, header: map[string]string{"Content-Type": jsonType, "Sec-Fetch-Site": "same-site"}, wantStatus: http.StatusForbidden},
		{name: "DELETE cross-site", method: http.MethodDelete, header: map[string]string{"Sec-Fetch-Site": "cross-site"}, wantStatus: http.StatusForbidden},
		// чужой сайт отсекается раньше, чем проверяется тип содержимого
		{name: "cross-site beats a wrong content type", method: http.MethodPost, header: map[string]string{"Content-Type": "text/plain", "Sec-Fetch-Site": "cross-site"}, wantStatus: http.StatusForbidden},

		// Content-Type
		{name: "POST with charset", method: http.MethodPost, header: map[string]string{"Content-Type": "application/json; charset=utf-8"}, wantStatus: http.StatusOK},
		{name: "POST with a type in other case", method: http.MethodPost, header: map[string]string{"Content-Type": "Application/JSON"}, wantStatus: http.StatusOK},
		{name: "POST as text/plain (a form can send it)", method: http.MethodPost, header: map[string]string{"Content-Type": "text/plain"}, wantStatus: http.StatusBadRequest},
		{name: "POST as a urlencoded form", method: http.MethodPost, header: map[string]string{"Content-Type": "application/x-www-form-urlencoded"}, wantStatus: http.StatusBadRequest},
		{name: "POST as multipart", method: http.MethodPost, header: map[string]string{"Content-Type": "multipart/form-data; boundary=x"}, wantStatus: http.StatusBadRequest},
		{name: "POST without Content-Type", method: http.MethodPost, wantStatus: http.StatusBadRequest},
		{name: "POST with a malformed Content-Type", method: http.MethodPost, header: map[string]string{"Content-Type": ";;;"}, wantStatus: http.StatusBadRequest},
		{name: "PATCH without Content-Type", method: http.MethodPatch, wantStatus: http.StatusBadRequest},
		{name: "PATCH as JSON", method: http.MethodPatch, header: map[string]string{"Content-Type": jsonType}, wantStatus: http.StatusOK},
		// DELETE тела не имеет: тип содержимого для него не требуется
		{name: "DELETE without Content-Type", method: http.MethodDelete, wantStatus: http.StatusOK},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			next := &spy{}
			// абсолютный URL задаёт r.Host = localhost:8080, с ним сравнивается Origin
			r := newRequest(tt.method, "http://localhost:8080/api/v1/auth/login")
			for key, value := range tt.header {
				r.Header.Set(key, value)
			}
			rec := httptest.NewRecorder()

			SameOrigin()(next).ServeHTTP(rec, r)

			if rec.Code != tt.wantStatus {
				t.Errorf("status = %d, want %d; body = %s", rec.Code, tt.wantStatus, rec.Body.String())
			}
			if next.called != (tt.wantStatus == http.StatusOK) {
				t.Errorf("next called = %v with status %d", next.called, rec.Code)
			}
		})
	}
}
