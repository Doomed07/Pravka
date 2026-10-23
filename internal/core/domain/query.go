package core_domain

import (
	"fmt"
	"time"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

const (
	DefaultLimit = 20
	MaxLimit     = 100
	DefaultTop   = 5
	MaxTop       = 100
)

func NormalizePagination(limit, offset *int) (int, int, error) {
	lim, off := DefaultLimit, 0

	if limit != nil {
		if *limit < 1 || *limit > MaxLimit {
			return 0, 0, fmt.Errorf("invalid 'limit' query param: %w", core_errors.ErrInvalidArgument)
		}
		lim = *limit
	}

	if offset != nil {
		if *offset < 0 {
			return 0, 0, fmt.Errorf("invalid 'offset' query param: %w", core_errors.ErrInvalidArgument)
		}
		off = *offset
	}

	return lim, off, nil
}

func ValidateFromToQuery(from, to *time.Time) error {
	if from != nil && to != nil && from.After(*to) {
		return fmt.Errorf("'from' is after 'to': %w", core_errors.ErrInvalidArgument)
	}

	return nil
}

func NormalizeTopQueryParam(top *int) (int, error) {
	t := DefaultTop

	if top != nil {
		if *top < 5 || *top > MaxTop {
			return 0, fmt.Errorf("invalid 'top' query param: %w", core_errors.ErrInvalidArgument)
		}
		t = *top
	}

	return t, nil
}
