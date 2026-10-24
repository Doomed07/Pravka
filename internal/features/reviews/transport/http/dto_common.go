package reviews_transport_http

import (
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

type ReviewDTO struct {
	ID           int            `json:"id"`
	CreatedAt    time.Time      `json:"created_at"`
	TheirsName   string         `json:"theirs_name"`
	BaseName     string         `json:"base_name"`
	Playbook     string         `json:"playbook"`
	PlaybookName string         `json:"playbook_name"`
	OurRole      string         `json:"our_role"`
	Side         string         `json:"side"`
	Counts       map[string]int `json:"counts"`
	Warnings     []string       `json:"warnings"`
}

func reviewDTOFromDomain(r core_domain.ContractReview) ReviewDTO {
	if r.Warnings == nil {
		r.Warnings = []string{}
	}
	return ReviewDTO{ID: r.ID, CreatedAt: r.CreatedAt, TheirsName: r.TheirsName, BaseName: r.BaseName, Playbook: r.Playbook,
		PlaybookName: r.PlaybookName, OurRole: r.OurRole, Side: r.Side, Counts: r.Counts, Warnings: r.Warnings}
}

func reviewsDTOFromDomain(revs []core_domain.ContractReview) []ReviewDTO {
	out := make([]ReviewDTO, len(revs))
	for i, r := range revs {
		out[i] = reviewDTOFromDomain(r)
	}
	return out
}
