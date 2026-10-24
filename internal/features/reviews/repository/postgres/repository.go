package reviews_repository_postgres

import (
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

type ReviewsRepository struct {
	pool core_postgres_pool.Pool
}

func NewReviewsRepository(pool core_postgres_pool.Pool) *ReviewsRepository {
	return &ReviewsRepository{pool: pool}
}
