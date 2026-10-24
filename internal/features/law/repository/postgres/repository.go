package law_repository_postgres

import (
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
)

// LawRepository — нормы закона в базе: пункты статей с поиском по словам и вектором.
type LawRepository struct {
	pool core_postgres_pool.Pool
}

func NewLawRepository(pool core_postgres_pool.Pool) *LawRepository {
	return &LawRepository{pool: pool}
}
