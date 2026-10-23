package core_http_request

import (
	"fmt"
	"net/http"
	"strconv"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func GetIntPathParam(r *http.Request, key string) (int, error) {
	path := r.PathValue(key)
	if path == "" {
		return 0, fmt.Errorf("No key:%s in path: %w",
			key, core_errors.ErrInvalidArgument)
	}

	id, err := strconv.Atoi(path)
	if err != nil {
		return 0, fmt.Errorf("path %s by key %s is not valid int: %v: %w",
			path, key, err, core_errors.ErrInvalidArgument)
	}

	return id, nil
}
