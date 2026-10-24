package reviews_service

import (
	"context"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
)

func (s *ReviewsService) Playbooks(ctx context.Context) ([]core_domain.Playbook, error) {
	return s.engine.Playbooks(ctx)
}
