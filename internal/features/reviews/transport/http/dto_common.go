package reviews_transport_http

import (
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

type ReviewDTO struct {
	ID           int            `json:"id"`
	CreatedAt    time.Time      `json:"created_at"`
	ProjectID    int            `json:"project_id"`
	ProjectName  string         `json:"project_name"`
	Round        int            `json:"round"`
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
	return ReviewDTO{ID: r.ID, CreatedAt: r.CreatedAt, ProjectID: r.ProjectID, ProjectName: r.ProjectName, Round: r.Round,
		TheirsName: r.TheirsName, BaseName: r.BaseName, Playbook: r.Playbook,
		PlaybookName: r.PlaybookName, OurRole: r.OurRole, Side: r.Side, Counts: r.Counts, Warnings: r.Warnings}
}

func reviewsDTOFromDomain(revs []core_domain.ContractReview) []ReviewDTO {
	out := make([]ReviewDTO, len(revs))
	for i, r := range revs {
		out[i] = reviewDTOFromDomain(r)
	}
	return out
}

type PlaybookDTO struct {
	Key  string `json:"key"`
	Name string `json:"name"`
	Role string `json:"role"`
}

func playbookDTOFromDomain(p core_domain.Playbook) PlaybookDTO {
	return PlaybookDTO{Key: p.Key, Name: p.Name, Role: p.Role}
}

func playbooksDTOFromDomain(list []core_domain.Playbook) []PlaybookDTO {
	out := make([]PlaybookDTO, len(list))
	for i, x := range list {
		out[i] = playbookDTOFromDomain(x)
	}
	return out
}

type ChoiceDTO struct {
	ChangeID string `json:"change_id"`
	Choice   string `json:"choice"`
	Text     string `json:"text"`
}

func choiceDTOFromDomain(c core_domain.ReviewChoice) ChoiceDTO {
	return ChoiceDTO{ChangeID: c.ChangeID, Choice: c.Choice, Text: c.Text}
}

func choicesDTOFromDomain(list []core_domain.ReviewChoice) []ChoiceDTO {
	out := make([]ChoiceDTO, len(list))
	for i, x := range list {
		out[i] = choiceDTOFromDomain(x)
	}
	return out
}

type PrecedentDTO struct {
	ChangeID   string    `json:"change_id"`
	ReviewID   int       `json:"review_id"`
	PastChange string    `json:"past_change"`
	TheirsName string    `json:"theirs_name"`
	CreatedAt  time.Time `json:"created_at"`
	Clause     string    `json:"clause"`
	Topic      string    `json:"topic"`
	Before     string    `json:"before"`
	After      string    `json:"after"`
	Choice     string    `json:"choice"`
	Text       string    `json:"text"`
	Same       bool      `json:"same"`
	Semantic   bool      `json:"semantic"`
	Score      float64   `json:"score"`
}

func precedentDTOFromDomain(p core_domain.Precedent) PrecedentDTO {
	return PrecedentDTO{ChangeID: p.ChangeID, ReviewID: p.ReviewID, PastChange: p.PastChangeID, TheirsName: p.TheirsName, CreatedAt: p.CreatedAt,
		Clause: p.Clause, Topic: p.Topic, Before: p.Before, After: p.After, Choice: p.Choice, Text: p.Text, Same: p.Same, Semantic: p.Semantic,
		Score: p.Score}
}

func precedentsDTOFromDomain(list []core_domain.Precedent) []PrecedentDTO {
	out := make([]PrecedentDTO, len(list))
	for i, x := range list {
		out[i] = precedentDTOFromDomain(x)
	}
	return out
}

type LawHintDTO struct {
	ChangeID string  `json:"change_id"`
	Article  string  `json:"article"`
	Point    string  `json:"point"`
	Title    string  `json:"title"`
	Chapter  string  `json:"chapter"`
	Edited   string  `json:"edited"`
	Text     string  `json:"text"`
	Distance float64 `json:"distance"`
}

func lawHintDTOFromDomain(l core_domain.LawHint) LawHintDTO {
	return LawHintDTO{ChangeID: l.ChangeID, Article: l.Article, Point: l.Point, Title: l.Title, Chapter: l.Chapter,
		Edited: l.Edited, Text: l.Text, Distance: l.Distance}
}

func lawHintsDTOFromDomain(list []core_domain.LawHint) []LawHintDTO {
	out := make([]LawHintDTO, len(list))
	for i, x := range list {
		out[i] = lawHintDTOFromDomain(x)
	}
	return out
}

type WordingDTO struct {
	ChangeID   string    `json:"change_id"`
	ReviewID   int       `json:"review_id"`
	TheirsName string    `json:"theirs_name"`
	CreatedAt  time.Time `json:"created_at"`
	Clause     string    `json:"clause"`
	Text       string    `json:"text"`
	Distance   float64   `json:"distance"`
}

func wordingDTOFromDomain(w core_domain.Wording) WordingDTO {
	return WordingDTO{ChangeID: w.ChangeID, ReviewID: w.ReviewID, TheirsName: w.TheirsName, CreatedAt: w.CreatedAt,
		Clause: w.Clause, Text: w.Text, Distance: w.Distance}
}

func wordingsDTOFromDomain(list []core_domain.Wording) []WordingDTO {
	out := make([]WordingDTO, len(list))
	for i, x := range list {
		out[i] = wordingDTOFromDomain(x)
	}
	return out
}

// RoleErrorDTO — ответ 422: юрист должен подтвердить роль и отправить договор ещё раз.
type RoleErrorDTO struct {
	Error   string `json:"error"`
	Message string `json:"message"`
	Role    string `json:"role"`
}

type RoundItemDTO struct {
	ChangeID string `json:"change_id"`
	Clause   string `json:"clause"`
	Kind     string `json:"kind"`
	Verdict  string `json:"verdict"`
	Silent   bool   `json:"silent"`
	Before   string `json:"before"`
	After    string `json:"after"`
}

type RoundTopicDTO struct {
	Topic    string         `json:"topic"`
	Verdicts map[string]int `json:"verdicts"`
	Silent   int            `json:"silent"`
	Deleted  int            `json:"deleted"`
	Items    []RoundItemDTO `json:"items"`
}

type RoundSummaryDTO struct {
	Topics    []RoundTopicDTO `json:"topics"`
	Technical int             `json:"technical"`
}

func roundItemDTOFromDomain(it core_domain.RoundItem) RoundItemDTO {
	return RoundItemDTO{ChangeID: it.ChangeID, Clause: it.Clause, Kind: it.Kind, Verdict: it.Verdict, Silent: it.Silent,
		Before: it.Before, After: it.After}
}

func roundSummaryDTOFromDomain(s core_domain.RoundSummary) RoundSummaryDTO {
	out := RoundSummaryDTO{Topics: make([]RoundTopicDTO, len(s.Topics)), Technical: s.Technical}
	for i, t := range s.Topics {
		items := make([]RoundItemDTO, len(t.Items))
		for j, it := range t.Items {
			items[j] = roundItemDTOFromDomain(it)
		}
		out.Topics[i] = RoundTopicDTO{Topic: t.Topic, Verdicts: t.Verdicts, Silent: t.Silent, Deleted: t.Deleted, Items: items}
	}
	return out
}

type ProjectDTO struct {
	ID           int       `json:"id"`
	Name         string    `json:"name"`
	CreatedAt    time.Time `json:"created_at"`
	Rounds       int       `json:"rounds"`
	LastReviewID int       `json:"last_review_id"`
	LastAt       time.Time `json:"last_at"`
	Playbook     string    `json:"playbook"`
	PlaybookName string    `json:"playbook_name"`
	OurRole      string    `json:"our_role"`
	ContractType string    `json:"contract_type"`
}

func projectDTOFromDomain(p core_domain.ProjectSummary) ProjectDTO {
	return ProjectDTO{ID: p.ID, Name: p.Name, CreatedAt: p.CreatedAt, Rounds: p.Rounds, LastReviewID: p.LastReviewID,
		LastAt: p.LastAt, Playbook: p.Playbook, PlaybookName: p.PlaybookName, OurRole: p.OurRole, ContractType: p.ContractType}
}

func projectsDTOFromDomain(list []core_domain.ProjectSummary) []ProjectDTO {
	out := make([]ProjectDTO, len(list))
	for i, p := range list {
		out[i] = projectDTOFromDomain(p)
	}
	return out
}

type ProjectRoundDTO struct {
	ReviewID   int       `json:"review_id"`
	Round      int       `json:"round"`
	CreatedAt  time.Time `json:"created_at"`
	TheirsName string    `json:"theirs_name"`
	BaseName   string    `json:"base_name"`
	Total      int       `json:"total"`
	New        int       `json:"new"`
	Repeat     int       `json:"repeat"`
	Returned   int       `json:"returned"`
	Closed     int       `json:"closed"`
}

type ProjectViewDTO struct {
	Project ProjectDTO        `json:"project"`
	Rounds  []ProjectRoundDTO `json:"rounds"`
}

func projectViewDTOFromDomain(v core_domain.ProjectView) ProjectViewDTO {
	out := ProjectViewDTO{Project: projectDTOFromDomain(v.Project), Rounds: make([]ProjectRoundDTO, len(v.Rounds))}
	for i, r := range v.Rounds {
		out.Rounds[i] = ProjectRoundDTO{ReviewID: r.ReviewID, Round: r.Round, CreatedAt: r.CreatedAt, TheirsName: r.TheirsName,
			BaseName: r.BaseName, Total: r.Total, New: r.New, Repeat: r.Repeat, Returned: r.Returned, Closed: r.Closed}
	}
	return out
}

type RoundLinkDTO struct {
	ChangeID     string `json:"change_id"`
	Relation     string `json:"relation"`
	Round        int    `json:"round"`
	ReviewID     int    `json:"review_id"`
	PastChangeID string `json:"past_change_id"`
	PastBefore   string `json:"past_before"`
	PastAfter    string `json:"past_after"`
	Decision     string `json:"decision"`
	DecisionText string `json:"decision_text"`
}

type RoundClosedDTO struct {
	Round        int    `json:"round"`
	ReviewID     int    `json:"review_id"`
	ChangeID     string `json:"change_id"`
	Clause       string `json:"clause"`
	Topic        string `json:"topic"`
	Before       string `json:"before"`
	After        string `json:"after"`
	Decision     string `json:"decision"`
	DecisionText string `json:"decision_text"`
}

type ReviewRoundsDTO struct {
	Project      ProjectDTO       `json:"project"`
	Round        int              `json:"round"`
	PrevReviewID int              `json:"prev_review_id"`
	Links        []RoundLinkDTO   `json:"links"`
	Closed       []RoundClosedDTO `json:"closed"`
}

func reviewRoundsDTOFromDomain(v core_domain.ReviewRounds) ReviewRoundsDTO {
	out := ReviewRoundsDTO{Project: projectDTOFromDomain(v.Project), Round: v.Round, PrevReviewID: v.PrevReviewID,
		Links: make([]RoundLinkDTO, len(v.Comparison.Links)), Closed: make([]RoundClosedDTO, len(v.Comparison.Closed))}
	for i, l := range v.Comparison.Links {
		out.Links[i] = RoundLinkDTO{ChangeID: l.ChangeID, Relation: l.Relation, Round: l.Round, ReviewID: l.ReviewID,
			PastChangeID: l.PastChangeID, PastBefore: l.PastBefore, PastAfter: l.PastAfter, Decision: l.Decision,
			DecisionText: l.DecisionText}
	}
	for i, c := range v.Comparison.Closed {
		out.Closed[i] = RoundClosedDTO{Round: c.Round, ReviewID: c.ReviewID, ChangeID: c.ChangeID, Clause: c.Clause, Topic: c.Topic,
			Before: c.Before, After: c.After, Decision: c.Decision, DecisionText: c.DecisionText}
	}
	return out
}
