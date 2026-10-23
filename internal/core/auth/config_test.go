package core_auth_test

import (
	"os"
	"testing"
	"time"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
)

var authEnvKeys = []string{"AUTH_SESSION_TTL", "AUTH_BCRYPT_COST", "AUTH_COOKIE_SECURE"}

// setAuthEnv задаёт переменные AUTH_* для одного теста. Ключ, которого нет в env,
// действительно удаляется из окружения: t.Setenv(key, "") дал бы «задано, но пусто»,
// а это другой случай (его проверяет отдельный кейс).
func setAuthEnv(t *testing.T, env map[string]string) {
	t.Helper()
	for _, key := range authEnvKeys {
		old, had := os.LookupEnv(key)
		t.Cleanup(func() {
			if had {
				os.Setenv(key, old)
			} else {
				os.Unsetenv(key)
			}
		})
		if value, ok := env[key]; ok {
			os.Setenv(key, value)
		} else {
			os.Unsetenv(key)
		}
	}
}

func TestNewConfig(t *testing.T) {
	tests := []struct {
		name    string
		env     map[string]string
		want    core_auth.Config
		wantErr bool
	}{
		{
			name: "defaults",
			env:  nil,
			want: core_auth.Config{SessionTTL: 720 * time.Hour, BcryptCost: 12, CookieSecure: false},
		},
		{
			name: "custom values",
			env: map[string]string{
				"AUTH_SESSION_TTL":   "1h",
				"AUTH_BCRYPT_COST":   "11",
				"AUTH_COOKIE_SECURE": "true",
			},
			want: core_auth.Config{SessionTTL: time.Hour, BcryptCost: 11, CookieSecure: true},
		},
		{
			name: "only secure is set, the rest are defaults",
			env:  map[string]string{"AUTH_COOKIE_SECURE": "true"},
			want: core_auth.Config{SessionTTL: 720 * time.Hour, BcryptCost: 12, CookieSecure: true},
		},
		{
			name: "lowest allowed cost",
			env:  map[string]string{"AUTH_BCRYPT_COST": "10"},
			want: core_auth.Config{SessionTTL: 720 * time.Hour, BcryptCost: 10},
		},
		{
			name: "highest allowed cost",
			env:  map[string]string{"AUTH_BCRYPT_COST": "14"},
			want: core_auth.Config{SessionTTL: 720 * time.Hour, BcryptCost: 14},
		},
		{
			name: "shortest ttl",
			env:  map[string]string{"AUTH_SESSION_TTL": "1ns"},
			want: core_auth.Config{SessionTTL: time.Nanosecond, BcryptCost: 12},
		},
		{name: "cost below range", env: map[string]string{"AUTH_BCRYPT_COST": "9"}, wantErr: true},
		{name: "cost above range", env: map[string]string{"AUTH_BCRYPT_COST": "15"}, wantErr: true},
		{name: "negative cost", env: map[string]string{"AUTH_BCRYPT_COST": "-12"}, wantErr: true},
		{name: "cost is not a number", env: map[string]string{"AUTH_BCRYPT_COST": "abc"}, wantErr: true},
		{name: "zero ttl", env: map[string]string{"AUTH_SESSION_TTL": "0s"}, wantErr: true},
		{name: "negative ttl", env: map[string]string{"AUTH_SESSION_TTL": "-1h"}, wantErr: true},
		{name: "ttl is not a duration", env: map[string]string{"AUTH_SESSION_TTL": "abc"}, wantErr: true},
		{name: "ttl without unit", env: map[string]string{"AUTH_SESSION_TTL": "720"}, wantErr: true},
		{name: "secure is not a bool", env: map[string]string{"AUTH_COOKIE_SECURE": "maybe"}, wantErr: true},
		// переменная задана, но пуста (так бывает в docker-compose с ${VAR} без значения):
		// значение по умолчанию в этом случае НЕ подставляется, поэтому в compose нужен ${VAR:-default}
		{name: "ttl is set but empty", env: map[string]string{"AUTH_SESSION_TTL": ""}, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			setAuthEnv(t, tt.env)

			got, err := core_auth.NewConfig()

			if tt.wantErr {
				if err == nil {
					t.Fatalf("NewConfig() = %+v, want error", got)
				}
				if got != (core_auth.Config{}) {
					t.Errorf("NewConfig() returned %+v together with an error, want zero value", got)
				}
				return
			}
			if err != nil {
				t.Fatalf("NewConfig() failed: %v", err)
			}
			if got != tt.want {
				t.Errorf("NewConfig() = %+v, want %+v", got, tt.want)
			}
		})
	}
}

func TestNewConfigMust(t *testing.T) {
	t.Run("valid config does not panic", func(t *testing.T) {
		setAuthEnv(t, nil)

		got := core_auth.NewConfigMust()

		if got.BcryptCost != 12 {
			t.Errorf("NewConfigMust() cost = %d, want 12", got.BcryptCost)
		}
	})

	t.Run("invalid config panics", func(t *testing.T) {
		setAuthEnv(t, map[string]string{"AUTH_BCRYPT_COST": "3"})

		defer func() {
			if recover() == nil {
				t.Error("NewConfigMust() did not panic on an invalid config")
			}
		}()
		core_auth.NewConfigMust()
	})
}
