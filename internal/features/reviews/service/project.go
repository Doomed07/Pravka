package reviews_service

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

// Project — история договора: раунды и что в каждом нового по сравнению с прошлыми.
func (s *ReviewsService) Project(ctx context.Context, userID, id int) (core_domain.ProjectView, error) {
	project, err := s.repo.GetProject(ctx, userID, id)
	if err != nil {
		return core_domain.ProjectView{}, err
	}
	rounds, err := s.repo.ListProjectRounds(ctx, userID, id)
	if err != nil {
		return core_domain.ProjectView{}, err
	}
	sources, current, err := roundSources(rounds)
	if err != nil {
		return core_domain.ProjectView{}, err
	}
	view := core_domain.ProjectView{Project: project, Rounds: make([]core_domain.ProjectRoundView, len(rounds))}
	for i, r := range rounds {
		cmp := core_domain.CompareRounds(current[i], sources[:i])
		view.Rounds[i] = core_domain.ProjectRoundView{ReviewID: r.ReviewID, Round: r.Round, CreatedAt: r.CreatedAt,
			TheirsName: r.TheirsName, BaseName: r.BaseName, Total: len(current[i]),
			New: cmp.Count(core_domain.RelationNew), Repeat: cmp.Count(core_domain.RelationRepeat),
			Returned: cmp.Count(core_domain.RelationReturned), Closed: len(cmp.Closed)}
	}
	return view, nil
}

// roundSources разбирает правки всех раундов: как прошлые раунды (с решениями юриста) и как правки самого раунда.
func roundSources(rounds []core_domain.ProjectRound) ([]core_domain.RoundSource, [][]core_domain.RoundChange, error) {
	sources := make([]core_domain.RoundSource, len(rounds))
	current := make([][]core_domain.RoundChange, len(rounds))
	for i, r := range rounds {
		changes, err := core_domain.ParseRoundChanges(r.Changes)
		if err != nil {
			return nil, nil, fmt.Errorf("раунд %d: %w", r.Round, err)
		}
		decisions := make(map[string]core_domain.ReviewChoice, len(r.Choices))
		for _, c := range r.Choices {
			decisions[c.ChangeID] = c
		}
		sources[i] = core_domain.RoundSource{ReviewID: r.ReviewID, Round: r.Round, Changes: changes, Decisions: decisions}
		current[i] = changes
	}
	return sources, current, nil
}
