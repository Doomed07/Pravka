package engine

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

// Parties — стороны договора и контрагент по преамбуле (быстро, без плейбука и модели). Ничего не сохраняет.
func (c *Client) Parties(ctx context.Context, theirs core_domain.UploadedFile, company string) (core_domain.DetectedParties, error) {
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	if company != "" {
		_ = mw.WriteField("company", company)
	}
	w, err := mw.CreateFormFile("theirs", "theirs.docx") // настоящее имя файла движку не нужно
	if err != nil {
		return core_domain.DetectedParties{}, err
	}
	if _, err := w.Write(theirs.Data); err != nil {
		return core_domain.DetectedParties{}, err
	}
	if err := mw.Close(); err != nil {
		return core_domain.DetectedParties{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.cfg.URL+"/parties", &buf)
	if err != nil {
		return core_domain.DetectedParties{}, err
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())
	resp, err := c.do(req)
	if err != nil {
		return core_domain.DetectedParties{}, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return core_domain.DetectedParties{}, fmt.Errorf("движок: чтение ответа: %v: %w", err, core_errors.ErrUnavailable)
	}
	if resp.StatusCode != http.StatusOK {
		var eb errorBody
		_ = json.Unmarshal(body, &eb)
		if resp.StatusCode == http.StatusBadRequest || resp.StatusCode == http.StatusRequestEntityTooLarge {
			return core_domain.DetectedParties{}, fmt.Errorf("%s: %w", eb.Message, core_errors.ErrInvalidArgument)
		}
		return core_domain.DetectedParties{}, fmt.Errorf("движок: статус %d: %s: %w", resp.StatusCode, eb.Message, core_errors.ErrUnavailable)
	}
	var raw struct {
		Parties      []struct{ Role, Name, INN string } `json:"parties"`
		Counterparty *struct{ Role, Name, INN string }  `json:"counterparty"`
		Ours         *struct{ Role, Name, INN string }  `json:"ours"`
		Title        string                             `json:"title"`
		ContractType string                             `json:"contract_type"`
		Playbook     string                             `json:"playbook"`
		Source       string                             `json:"source"`
	}
	if err := json.Unmarshal(body, &raw); err != nil {
		return core_domain.DetectedParties{}, fmt.Errorf("движок: разбор ответа: %w", err)
	}
	out := core_domain.DetectedParties{Parties: make([]core_domain.DetectedParty, len(raw.Parties))}
	for i, p := range raw.Parties {
		out.Parties[i] = core_domain.DetectedParty{Role: p.Role, Name: p.Name, INN: p.INN}
	}
	if raw.Counterparty != nil {
		out.Counterparty = &core_domain.DetectedParty{Role: raw.Counterparty.Role, Name: raw.Counterparty.Name, INN: raw.Counterparty.INN}
	}
	if raw.Ours != nil {
		out.Ours = &core_domain.DetectedParty{Role: raw.Ours.Role, Name: raw.Ours.Name, INN: raw.Ours.INN}
	}
	out.Title, out.ContractType, out.Playbook, out.Source = raw.Title, raw.ContractType, raw.Playbook, raw.Source
	return out, nil
}
