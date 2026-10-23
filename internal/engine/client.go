// Package engine — клиент внутреннего HTTP-сервиса движка «Правки» (Python, `python -m pravki engine`).
package engine

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	"github.com/kelseyhightower/envconfig"
)

type Config struct {
	URL     string        `envconfig:"URL" default:"http://engine:8000"`
	Token   string        `envconfig:"TOKEN"`
	Timeout time.Duration `envconfig:"TIMEOUT" default:"5m"`
}

func NewConfigMust() Config {
	var c Config
	if err := envconfig.Process("ENGINE", &c); err != nil {
		panic(fmt.Errorf("get engine config: %w", err))
	}
	return c
}

type Client struct {
	cfg  Config
	http *http.Client
}

func NewClient(cfg Config) *Client {
	return &Client{cfg: cfg, http: &http.Client{Timeout: cfg.Timeout}}
}

// Result — ответ движка на успешный разбор.
type Result struct {
	Counts       map[string]int  `json:"counts"`
	Warnings     []string        `json:"warnings"`
	Side         string          `json:"side"`
	PlaybookName string          `json:"playbook_name"`
	OurRole      string          `json:"our_role"`
	ReportHTML   string          `json:"report_html"`
	ReportXLSX   string          `json:"report_xlsx"` // base64
	Changes      json.RawMessage `json:"changes"`
	Document     json.RawMessage `json:"document"`     // единая версия договора: абзацы с правками
	UnifiedDOCX  string          `json:"unified_docx"` // base64: единая версия в Word с примечаниями
	Unified      []byte          `json:"-"`            // UnifiedDOCX после декодирования
}

type errorBody struct {
	Error   string `json:"error"`
	Message string `json:"message"`
	Role    string `json:"role"`
}

// RoleError — движок не стал разбирать договор: сторона не подтверждена. Role — роль плейбука для подтверждения.
type RoleError struct {
	Message string
	Role    string
}

func (e *RoleError) Error() string { return e.Message }
func (e *RoleError) Unwrap() error { return core_errors.ErrUnprocessable }

func (c *Client) do(req *http.Request) (*http.Response, error) {
	if c.cfg.Token != "" {
		req.Header.Set("X-Engine-Token", c.cfg.Token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("движок разбора недоступен: %v: %w", err, core_errors.ErrUnavailable)
	}
	return resp, nil
}

func (c *Client) Playbooks(ctx context.Context) ([]core_domain.Playbook, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.cfg.URL+"/playbooks", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("движок: список плейбуков: статус %d: %w", resp.StatusCode, core_errors.ErrUnavailable)
	}
	var raw []struct{ Key, Name, Role string }
	if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
		return nil, fmt.Errorf("движок: разбор списка плейбуков: %w", err)
	}
	out := make([]core_domain.Playbook, 0, len(raw))
	for _, p := range raw {
		out = append(out, core_domain.Playbook{Key: p.Key, Name: p.Name, Role: p.Role})
	}
	return out, nil
}

func (c *Client) Review(ctx context.Context, r core_domain.ReviewRequest) (Result, []byte, error) {
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	for k, v := range map[string]string{"playbook": r.Playbook, "our_authors": r.OurAuthors, "company": r.Company,
		"confirm_role": r.ConfirmRole} {
		if v != "" {
			_ = mw.WriteField(k, v)
		}
	}
	files := map[string]*core_domain.UploadedFile{"theirs": &r.Theirs, "base": r.Base}
	for field, f := range files {
		if f == nil {
			continue
		}
		w, err := mw.CreateFormFile(field, field+".docx") // настоящие имена файлов движку не нужны
		if err != nil {
			return Result{}, nil, err
		}
		if _, err := w.Write(f.Data); err != nil {
			return Result{}, nil, err
		}
	}
	if err := mw.Close(); err != nil {
		return Result{}, nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.cfg.URL+"/review", &buf)
	if err != nil {
		return Result{}, nil, err
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())
	resp, err := c.do(req)
	if err != nil {
		return Result{}, nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 200<<20))
	if err != nil {
		return Result{}, nil, fmt.Errorf("движок: чтение ответа: %v: %w", err, core_errors.ErrUnavailable)
	}
	if resp.StatusCode != http.StatusOK {
		var eb errorBody
		_ = json.Unmarshal(body, &eb)
		switch {
		case resp.StatusCode == http.StatusUnprocessableEntity:
			return Result{}, nil, &RoleError{Message: eb.Message, Role: eb.Role}
		case resp.StatusCode == http.StatusBadRequest || resp.StatusCode == http.StatusRequestEntityTooLarge:
			return Result{}, nil, fmt.Errorf("%s: %w", eb.Message, core_errors.ErrInvalidArgument)
		default:
			return Result{}, nil, fmt.Errorf("движок: статус %d: %s: %w", resp.StatusCode, eb.Message, core_errors.ErrUnavailable)
		}
	}
	var res Result
	if err := json.Unmarshal(body, &res); err != nil {
		return Result{}, nil, fmt.Errorf("движок: разбор ответа: %w", err)
	}
	xlsx, err := base64.StdEncoding.DecodeString(res.ReportXLSX)
	if err != nil {
		return Result{}, nil, fmt.Errorf("движок: Excel в ответе повреждён: %w", err)
	}
	if res.Unified, err = base64.StdEncoding.DecodeString(res.UnifiedDOCX); err != nil {
		return Result{}, nil, fmt.Errorf("движок: единая версия в ответе повреждена: %w", err)
	}
	res.UnifiedDOCX = ""
	return res, xlsx, nil
}

// AnswerResult — ответ контрагенту в Word и счётчики применённых решений.
type AnswerResult struct {
	DOCX  []byte
	Stats map[string]int
}

// Answer собирает ответ контрагенту: единая версия (docx и абзацы JSON) + правки разбора (JSON) + решения юриста.
func (c *Client) Answer(ctx context.Context, unified, document, changes []byte, choices []core_domain.ReviewChoice, author string) (AnswerResult, error) {
	sel := make(map[string]map[string]string, len(choices))
	for _, ch := range choices {
		sel[ch.ChangeID] = map[string]string{"choice": ch.Choice, "text": ch.Text}
	}
	selJSON, err := json.Marshal(sel)
	if err != nil {
		return AnswerResult{}, err
	}
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	for k, v := range map[string]string{"changes": string(changes), "choices": string(selJSON), "author": author,
		"document": string(document)} {
		_ = mw.WriteField(k, v)
	}
	w, err := mw.CreateFormFile("unified", "unified.docx")
	if err != nil {
		return AnswerResult{}, err
	}
	if _, err := w.Write(unified); err != nil {
		return AnswerResult{}, err
	}
	if err := mw.Close(); err != nil {
		return AnswerResult{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.cfg.URL+"/answer", &buf)
	if err != nil {
		return AnswerResult{}, err
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())
	resp, err := c.do(req)
	if err != nil {
		return AnswerResult{}, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 200<<20))
	if err != nil {
		return AnswerResult{}, fmt.Errorf("движок: чтение ответа: %v: %w", err, core_errors.ErrUnavailable)
	}
	if resp.StatusCode != http.StatusOK {
		var eb errorBody
		_ = json.Unmarshal(body, &eb)
		if resp.StatusCode == http.StatusBadRequest {
			return AnswerResult{}, fmt.Errorf("%s: %w", eb.Message, core_errors.ErrInvalidArgument)
		}
		return AnswerResult{}, fmt.Errorf("движок: статус %d: %s: %w", resp.StatusCode, eb.Message, core_errors.ErrUnavailable)
	}
	var raw struct {
		DOCX  string         `json:"answer_docx"`
		Stats map[string]int `json:"stats"`
	}
	if err := json.Unmarshal(body, &raw); err != nil {
		return AnswerResult{}, fmt.Errorf("движок: разбор ответа: %w", err)
	}
	docx, err := base64.StdEncoding.DecodeString(raw.DOCX)
	if err != nil {
		return AnswerResult{}, fmt.Errorf("движок: файл ответа повреждён: %w", err)
	}
	return AnswerResult{DOCX: docx, Stats: raw.Stats}, nil
}
