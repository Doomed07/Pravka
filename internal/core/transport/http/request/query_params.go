package core_http_request

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
)

func GetIntQueryParam(r *http.Request, key string) (*int, error) {
	param := r.URL.Query().Get(key)
	if param == "" {
		return nil, nil
	}

	queryParam, err := strconv.Atoi(param)
	if err != nil {
		return nil, fmt.Errorf(
			"invalid int: param: %s; key: %s; err: %v; typeErr: %w",
			param, key, err, core_errors.ErrInvalidArgument,
		)
	}

	return &queryParam, nil
}

func GetStrQueryParam(r *http.Request, key string) *string {
	param := strings.TrimSpace(r.URL.Query().Get(key))
	if param == "" {
		return nil
	}

	return &param
}

func GetLimitOffsetQueryParam(r *http.Request) (*int, *int, error) {
	const (
		limitQueryParam  = "limit"
		offsetQueryParam = "offset"
	)

	limit, err := GetIntQueryParam(r, limitQueryParam)
	if err != nil {
		return nil, nil, fmt.Errorf("get 'limit' query param: %w", err)
	}

	offset, err := GetIntQueryParam(r, offsetQueryParam)
	if err != nil {
		return nil, nil, fmt.Errorf("get 'offset' query param: %w", err)
	}
	return limit, offset, nil
}

func getBoolQueryParam(r *http.Request, key string) (*bool, error) {
	param := r.URL.Query().Get(key)
	if param == "" {
		return nil, nil
	}

	queryParam, err := strconv.ParseBool(param)
	if err != nil {
		return nil, fmt.Errorf("invalid bool param: %s; key: %s; err: %v; typeErr:%w",
			param, key, err, core_errors.ErrInvalidArgument)
	}

	return &queryParam, nil
}

func GetReadQueryParam(r *http.Request) (*bool, error) {
	const readQueryParam = "read"

	read, err := getBoolQueryParam(r, readQueryParam)
	if err != nil {
		return nil, fmt.Errorf("get read query param: %w", err)
	}

	return read, nil
}

func getDateQueryParam(r *http.Request, key string) (*time.Time, error) {
	param := r.URL.Query().Get(key)
	if param == "" {
		return nil, nil
	}

	date, err := time.ParseInLocation(time.DateOnly, param, time.Local)
	if err != nil {
		return nil, fmt.Errorf("param=%s by key=%s not valid date:%v:%w",
			param, key, err, core_errors.ErrInvalidArgument)
	}

	return &date, nil
}

func GetFromToQueryParam(r *http.Request) (*time.Time, *time.Time, error) {
	const (
		fromQueryParam = "from"
		toQueryParam   = "to"
	)

	from, err := getDateQueryParam(r, fromQueryParam)
	if err != nil {
		return nil, nil, fmt.Errorf("get 'from' query param:%w", err)
	}

	to, err := getDateQueryParam(r, toQueryParam)
	if err != nil {
		return nil, nil, fmt.Errorf("get 'to' query param:%w", err)
	}

	return from, to, nil
}
