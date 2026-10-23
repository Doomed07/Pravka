package core_logger

import (
	"fmt"

	"github.com/kelseyhightower/envconfig"
)

type Config struct {
	Lvl    string `envconfig:"LVL" default:"DEBUG"`
	Folder string `envconfig:"FOLDER" required:"true"`
}

func NewConfig() (Config, error) {
	var config Config

	if err := envconfig.Process("LOGGER", &config); err != nil {
		return Config{}, fmt.Errorf("process envconfig: %w", err)
	}
	return config, nil
}

func NewConfigMust() Config {
	config, err := NewConfig()
	if err != nil {
		err = fmt.Errorf("get logger cofig: %w", err)
		panic(err)
	}
	return config
}
