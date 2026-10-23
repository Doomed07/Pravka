package core_postgres_pool

import (
	"errors"
	"fmt"
)

var (
	ErrNoRows              = errors.New("no rows")
	ErrUniqueViolation     = errors.New("unique violation")
	ErrForeignKeyViolation = errors.New("foreign key violation")
	ErrUnknown             = errors.New("unknown error")
)

// ConstraintError — нарушение ограничения БД вместе с его именем из схемы.
type ConstraintError struct {
	Kind       error  // ErrUniqueViolation или ErrForeignKeyViolation
	Constraint string // например "users_email_key"
	Err        error  // исходная ошибка драйвера (для текста и логов)
}

func (e *ConstraintError) Error() string { return fmt.Sprintf("%v: %v", e.Kind, e.Err) }

// Unwrap возвращает Kind, поэтому errors.Is(err, ErrUniqueViolation) работает как раньше.
func (e *ConstraintError) Unwrap() error { return e.Kind }
