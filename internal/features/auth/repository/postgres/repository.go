package auth_repository_postgres

import core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"

type AuthRepository struct {
	pool core_postgres_pool.Pool
}

func NewAuthRepository(pool core_postgres_pool.Pool) *AuthRepository {
	return &AuthRepository{pool: pool}
}
