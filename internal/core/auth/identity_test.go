package core_auth_test

import (
	"context"
	"testing"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
)

func TestIdentityFromCtx_Anonymous(t *testing.T) {
	// аноним: в контексте ничего нет — ok == false и нулевая Identity, без паники
	got, ok := core_auth.IdentityFromCtx(context.Background())

	if ok {
		t.Error("IdentityFromCtx() ok = true, want false")
	}
	if got != (core_auth.Identity{}) {
		t.Errorf("IdentityFromCtx() = %+v, want zero value", got)
	}
}

func TestWithIdentity(t *testing.T) {
	tests := []struct {
		name     string
		identity core_auth.Identity
	}{
		{
			name: "basic identity",
			identity: core_auth.Identity{
				UserID:   7,
				Username: "kant",
				Email:    "user@example.ru",
			},
		},
		{
			name: "zero user id",
			identity: core_auth.Identity{
				UserID:   0,
				Username: "x"},
		},
		{
			name: "empty username",
			identity: core_auth.Identity{
				UserID: 3},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctx := core_auth.WithIdentity(t.Context(), tt.identity)

			got, ok := core_auth.IdentityFromCtx(ctx)
			if !ok {
				t.Fatal("IdentityFromCtx() ok = false, want true")
			}
			if got != tt.identity {
				t.Errorf("IdentityFromCtx() = %+v, want %+v", got, tt.identity)
			}
		})
	}
}

func TestIdentityFromCtx_ChildContext(t *testing.T) {
	// middleware кладёт Identity, а обработчик получает уже дочерний контекст запроса
	ctx := core_auth.WithIdentity(t.Context(), core_auth.Identity{UserID: 7, Username: "kant"})
	child, cancel := context.WithCancel(ctx)
	defer cancel()

	got, ok := core_auth.IdentityFromCtx(child)
	if !ok || got.UserID != 7 {
		t.Errorf("IdentityFromCtx(child) = %+v, %v; want UserID 7, true", got, ok)
	}
}

func TestWithIdentity_Overwrite(t *testing.T) {
	// более поздняя запись перекрывает предыдущую
	ctx := core_auth.WithIdentity(t.Context(), core_auth.Identity{UserID: 1, Username: "a"})
	ctx = core_auth.WithIdentity(ctx, core_auth.Identity{UserID: 2, Username: "b"})

	got, _ := core_auth.IdentityFromCtx(ctx)
	if got.UserID != 2 {
		t.Errorf("UserID = %d, want 2", got.UserID)
	}
}
