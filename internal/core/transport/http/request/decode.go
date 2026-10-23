package core_http_request

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"

	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	"github.com/go-playground/validator/v10"
)

var requestValidator = validator.New()

// MaxRequestBodyBytes — предел размера тела запроса. Все наши запросы крошечные
// (самое длинное — рецензия до 5000 символов), 1 МиБ с огромным запасом.
const MaxRequestBodyBytes = 1 << 20

type Validatable interface {
	Validate() error
}

func DecodeAndValidateRequest(r *http.Request, dest any) error {
	body := http.MaxBytesReader(nil, r.Body, MaxRequestBodyBytes)

	if err := json.NewDecoder(body).Decode(dest); err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			return fmt.Errorf("request body is larger than %d bytes: %w",
				MaxRequestBodyBytes, core_errors.ErrInvalidArgument)
		}
		return fmt.Errorf("decode JSON: %v: %w", err, core_errors.ErrInvalidArgument)
	}

	var err error

	v, ok := dest.(Validatable)
	if ok {
		err = v.Validate()
	} else {
		err = requestValidator.Struct(dest)
	}

	if err != nil {
		return fmt.Errorf("request validation: %v: %w", err, core_errors.ErrInvalidArgument)
	}

	return nil

}
