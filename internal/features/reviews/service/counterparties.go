package reviews_service

import (
	"context"
	"fmt"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

// Counterparties — контрагенты пользователя.
func (s *ReviewsService) Counterparties(ctx context.Context, userID int) ([]core_domain.CounterpartySummary, error) {
	return s.repo.ListCounterparties(ctx, userID, MaxLimit)
}

// Counterparty — страница контрагента: он сам и его договоры.
func (s *ReviewsService) Counterparty(ctx context.Context, userID, id int) (core_domain.CounterpartyView, error) {
	cp, err := s.repo.GetCounterparty(ctx, userID, id)
	if err != nil {
		return core_domain.CounterpartyView{}, err
	}
	projects, err := s.repo.ListCounterpartyProjects(ctx, userID, id)
	if err != nil {
		return core_domain.CounterpartyView{}, err
	}
	return core_domain.CounterpartyView{Counterparty: cp, Projects: projects}, nil
}

// RenameCounterparty меняет название и ИНН контрагента (папка на диске не меняется).
func (s *ReviewsService) RenameCounterparty(ctx context.Context, userID, id int, name, inn string) error {
	name, err := core_domain.CounterpartyName(name)
	if err != nil {
		return err
	}
	if inn, err = core_domain.CounterpartyINN(inn); err != nil {
		return err
	}
	return s.repo.RenameCounterparty(ctx, userID, id, name, inn)
}

// MoveProject переносит договор к другому контрагенту.
func (s *ReviewsService) MoveProject(ctx context.Context, userID, projectID, counterpartyID int) error {
	if projectID <= 0 || counterpartyID <= 0 {
		return fmt.Errorf("укажите договор и контрагента: %w", core_errors.ErrInvalidArgument)
	}
	return s.repo.MoveProject(ctx, userID, projectID, counterpartyID)
}

// DetectParties — стороны договора и контрагент по преамбуле первой версии. Ничего не сохраняет. company — ИНН или
// наименование нашей компании: по нему находится, какая сторона наша.
func (s *ReviewsService) DetectParties(ctx context.Context, theirs core_domain.UploadedFile, company string) (core_domain.DetectedParties, error) {
	theirs.Name = core_domain.CleanFileName(theirs.Name)
	req := core_domain.ReviewRequest{Theirs: theirs}
	if err := req.Validate(); err != nil {
		return core_domain.DetectedParties{}, err
	}
	return s.engine.Parties(ctx, theirs, company)
}
