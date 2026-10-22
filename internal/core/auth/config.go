package core_auth

import (
	"fmt"
	"time"

	"github.com/kelseyhightower/envconfig"
)

type Config struct {
	SessionTTL   time.Duration `envconfig:"SESSION_TTL" default:"720h"`
	BcryptCost   int           `envconfig:"BCRYPT_COST" default:"12"`
	CookieSecure bool          `envconfig:"COOKIE_SECURE" default:"false"`
	// SignupCode — код приглашения. Если задан, зарегистрироваться можно только с ним: сервис с договорами
	// не должен быть открыт для всех, когда он запущен на удалённом сервере.
	SignupCode string `envconfig:"SIGNUP_CODE"`
}

func NewConfig() (Config, error) {
	var config Config
	if err := envconfig.Process("AUTH", &config); err != nil {
		return Config{}, fmt.Errorf("process config: %w", err)
	}
	if config.SessionTTL <= 0 {
		return Config{}, fmt.Errorf("AUTH_SESSION_TTL must be positive, got %s", config.SessionTTL)
	}
	if config.BcryptCost < 10 || config.BcryptCost > 14 {
		return Config{}, fmt.Errorf("AUTH_BCRYPT_COST must be in 10..14, got %d", config.BcryptCost)
	}
	return config, nil
}

func NewConfigMust() Config {
	config, err := NewConfig()
	if err != nil {
		err = fmt.Errorf("get auth config: %w", err)
		panic(err)
	}

	return config
}
