package core_http_request

import (
	"errors"
	"io"
	"net/http/httptest"
	"strings"
	"testing"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

type tagValidatedRequest struct {
	BookID int `json:"book_id" validate:"required,min=1"`
}

type selfValidatedRequest struct {
	Name string `json:"name"`
}

func (r selfValidatedRequest) Validate() error {
	if r.Name == "" {
		return errors.New("name is empty")
	}
	return nil
}

func TestDecodeAndValidateRequest(t *testing.T) {
	tests := []struct {
		name    string
		body    string
		dest    any
		wantErr bool
	}{
		{name: "valid body, validator tags", body: `{"book_id": 1}`, dest: &tagValidatedRequest{}},
		{name: "invalid JSON", body: `{"book_id": `, dest: &tagValidatedRequest{}, wantErr: true},
		{name: "wrong type", body: `{"book_id": "one"}`, dest: &tagValidatedRequest{}, wantErr: true},
		{name: "validator tag fails", body: `{"book_id": 0}`, dest: &tagValidatedRequest{}, wantErr: true},
		{name: "missing required field", body: `{}`, dest: &tagValidatedRequest{}, wantErr: true},
		// если тип реализует Validatable, вызывается его Validate(), а не теги
		{name: "valid body, own Validate()", body: `{"name": "kek"}`, dest: &selfValidatedRequest{}},
		{name: "own Validate() fails", body: `{"name": ""}`, dest: &selfValidatedRequest{}, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("POST", "/", strings.NewReader(tt.body))
			gotErr := DecodeAndValidateRequest(r, tt.dest)

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Errorf("DecodeAndValidateRequest() error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				return
			}

			if gotErr != nil {
				t.Errorf("DecodeAndValidateRequest() failed: %v", gotErr)
			}
		})
	}
}

const (
	nameBodyPrefix = `{"name":"`
	nameBodySuffix = `"}`
)

// nameBodyOfSize собирает JSON {"name":"aaa…"} длиной ровно size байт.
func nameBodyOfSize(size int) string {
	return nameBodyPrefix + strings.Repeat("a", size-len(nameBodyPrefix)-len(nameBodySuffix)) + nameBodySuffix
}

func TestDecodeAndValidateRequest_BodySize(t *testing.T) {
	const mib = 1 << 20

	tests := []struct {
		name     string
		body     string
		wantErr  bool
		wantText string // что должно быть в тексте ошибки; пусто — не проверяем
	}{
		{name: "small body", body: nameBodyOfSize(1000)},
		{name: "one byte below the limit", body: nameBodyOfSize(MaxRequestBodyBytes - 1)},
		{name: "exactly at the limit", body: nameBodyOfSize(MaxRequestBodyBytes)},
		{name: "one byte over the limit", body: nameBodyOfSize(MaxRequestBodyBytes + 1), wantErr: true, wantText: "larger than"},
		{name: "far over the limit", body: nameBodyOfSize(5 * mib), wantErr: true, wantText: "larger than"},
		// строка не закрыта, JSON невалиден, но раньше, чем это станет ясно, срабатывает лимит
		{name: "huge unterminated string", body: nameBodyPrefix + strings.Repeat("a", 2*mib), wantErr: true, wantText: "larger than"},
		// json.Decoder останавливается на конце значения и хвост не читает
		{name: "valid JSON followed by a huge tail", body: `{"name":"kek"}` + strings.Repeat("x", 3*mib)},
		// обычная ошибка разбора не должна маскироваться под «слишком большое тело»
		{name: "broken JSON is still a decode error", body: `{"name": `, wantErr: true, wantText: "decode JSON"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("POST", "/", strings.NewReader(tt.body))
			var dest selfValidatedRequest

			gotErr := DecodeAndValidateRequest(r, &dest)

			if tt.wantErr {
				if !errors.Is(gotErr, core_errors.ErrInvalidArgument) {
					t.Fatalf("error = %v, want wrapped core_errors.ErrInvalidArgument", gotErr)
				}
				if tt.wantText != "" && !strings.Contains(gotErr.Error(), tt.wantText) {
					t.Errorf("error = %q, want it to contain %q", gotErr.Error(), tt.wantText)
				}
				return
			}
			if gotErr != nil {
				t.Fatalf("DecodeAndValidateRequest() failed: %v", gotErr)
			}
			if dest.Name == "" {
				t.Error("body was accepted but the field was not decoded")
			}
		})
	}
}

// endlessBody — тело без конца. Считает, сколько байт у него прочитали, и обрывается само
// (ошибкой, не похожей на «слишком большое тело»), если лимит не сработал: тест не повиснет.
type endlessBody struct{ read int }

func (b *endlessBody) Read(p []byte) (int, error) {
	if b.read > 3*MaxRequestBodyBytes {
		return 0, io.ErrUnexpectedEOF
	}
	for i := range p {
		p[i] = 'a'
	}
	b.read += len(p)
	return len(p), nil
}

// Лимит защищает память: из бесконечного потока сервер прочитает не больше лимита (плюс байт,
// по которому понимает, что тело длиннее), а не будет читать, пока не кончится память.
func TestDecodeAndValidateRequest_StopsReadingAtTheLimit(t *testing.T) {
	endless := &endlessBody{}
	r := httptest.NewRequest("POST", "/", io.MultiReader(strings.NewReader(nameBodyPrefix), endless))

	err := DecodeAndValidateRequest(r, &selfValidatedRequest{})

	if !errors.Is(err, core_errors.ErrInvalidArgument) || !strings.Contains(err.Error(), "larger than") {
		t.Fatalf("error = %v, want a 'larger than' invalid-argument error", err)
	}
	if endless.read > MaxRequestBodyBytes+1 {
		t.Errorf("read %d bytes from an endless body, want at most %d", endless.read, MaxRequestBodyBytes+1)
	}
}

// Предел 1 МиБ описан в документации и плане: менять его надо осознанно, а не случайной правкой.
func TestMaxRequestBodyBytes(t *testing.T) {
	if MaxRequestBodyBytes != 1<<20 {
		t.Errorf("MaxRequestBodyBytes = %d, want %d (1 MiB)", MaxRequestBodyBytes, 1<<20)
	}
}
