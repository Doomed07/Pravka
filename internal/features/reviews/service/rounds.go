package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// Rounds — как правки разбора связаны с прошлыми раундами того же договора: повторные, возвращения к пункту, снятые.
// Только подсказка: решения по правкам принимает плейбук и юрист.
func (s *ReviewsService) Rounds(ctx context.Context, userID, id int) (core_domain.ReviewRounds, error) {
	rev, err := s.repo.GetReview(ctx, userID, id)
	if err != nil {
		return core_domain.ReviewRounds{}, err
	}
	project, err := s.repo.GetProject(ctx, userID, rev.ProjectID)
	if err != nil {
		return core_domain.ReviewRounds{}, err
	}
	rounds, err := s.repo.ListProjectRounds(ctx, userID, rev.ProjectID)
	if err != nil {
		return core_domain.ReviewRounds{}, err
	}
	sources, current, err := roundSources(rounds)
	if err != nil {
		return core_domain.ReviewRounds{}, err
	}
	out := core_domain.ReviewRounds{Project: project, Round: rev.Round}
	for i, r := range rounds {
		if r.ReviewID != id {
			continue
		}
		if i > 0 {
			out.PrevReviewID = rounds[i-1].ReviewID
		}
		out.Comparison = core_domain.CompareRounds(current[i], sources[:i])
	}
	return out, nil
}
