package core_auth

import "context"

// Identity — вошедший пользователь. Кладётся в контекст middleware Authenticate.
type Identity struct {
	UserID   int
	Username string
	Email    string
}

type identityContextKey struct{}

var identityKey = identityContextKey{}

func WithIdentity(ctx context.Context, identity Identity) context.Context {
	return context.WithValue(ctx, identityKey, identity)
}

// IdentityFromCtx возвращает (Identity, false) для анонима. В отличие от FromCtx
// логгера, здесь НЕТ паники: аноним — обычная ситуация, а не ошибка программиста.
func IdentityFromCtx(ctx context.Context) (Identity, bool) {
	identity, ok := ctx.Value(identityKey).(Identity)
	return identity, ok
}
