package core_http_types

import (
	"encoding/json"

	"github.com/Doomed07/Pravka/internal/core/domain"
)

type Nullable[T any] struct {
	core_domain.Nullable[T]
}

func (n *Nullable[T]) UnmarshalJSON(b []byte) error {
	n.Set = true

	if string(b) == "null" {
		n.Value = nil
		return nil
	}

	var value T
	if err := json.Unmarshal(b, &value); err != nil {
		return err
	}

	n.Value = &value

	return nil
}

func (n *Nullable[T]) ToDomain() core_domain.Nullable[T] {
	return core_domain.Nullable[T]{
		Value: n.Value,
		Set:   n.Set,
	}
}
