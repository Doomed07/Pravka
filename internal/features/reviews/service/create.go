package reviews_service

import (
	"context"
	"errors"
	"fmt"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
	"github.com/Doomed07/Pravka/internal/engine"
)

// Create отправляет договор движку и сохраняет результат. Исходные docx не сохраняются: в базе остаются только отчёты.
func (s *ReviewsService) Create(ctx context.Context, userID int, req core_domain.ReviewRequest) (core_domain.ContractReview, error) {
	req.Theirs.Name = core_domain.CleanFileName(req.Theirs.Name)
	if req.Base != nil {
		req.Base.Name = core_domain.CleanFileName(req.Base.Name)
	}
	if err := req.Validate(); err != nil {
		core_metrics.ReviewsFailed.WithLabelValues("invalid").Inc()
		return core_domain.ContractReview{}, err
	}
	start := time.Now()
	res, xlsx, err := s.engine.Review(ctx, req)
	core_metrics.ReviewDuration.Observe(time.Since(start).Seconds())
	if err != nil {
		reason := "engine"
		var re *engine.RoleError
		switch {
		case errors.As(err, &re):
			reason = "role"
		case errors.Is(err, core_errors.ErrInvalidArgument):
			reason = "bad_file"
		}
		core_metrics.ReviewsFailed.WithLabelValues(reason).Inc()
		return core_domain.ContractReview{}, err
	}
	rev := core_domain.ContractReview{
		UserID: userID, TheirsName: req.Theirs.Name, Playbook: req.Playbook, PlaybookName: res.PlaybookName,
		OurRole: res.OurRole, ContractType: res.ContractType, Side: res.Side, Counts: res.Counts, Warnings: res.Warnings,
	}
	if req.Base != nil {
		rev.BaseName = req.Base.Name
	}
	out, err := s.repo.CreateReview(ctx, rev, core_domain.ReviewFiles{
		ReportHTML: []byte(res.ReportHTML), ReportXLSX: xlsx, Changes: res.Changes,
		Document: res.Document, Unified: res.Unified,
	})
	if err != nil {
		return core_domain.ContractReview{}, fmt.Errorf("save review: %w", err)
	}
	core_metrics.ReviewsCreated.Inc()
	select {
	case s.nudge <- struct{}{}:
	default:
	}
	return out, nil
}
