package auth_service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	"golang.org/x/crypto/bcrypt"
)

var (
	testNow = time.Date(2026, 10, 8, 12, 0, 0, 0, time.UTC)
	errBoom = errors.New("db is down")
)

const testTTL = 720 * time.Hour

type storedSession struct {
	session core_domain.Session
	user    core_domain.User
}

// fakeAuthRepository — репозиторий в памяти: хранит пользователей и сессии,
// запоминает, с чем его вызвали, и по запросу возвращает заранее заданную ошибку.
// База и сеть для теста сервиса не нужны.
type fakeAuthRepository struct {
	creds    map[string]core_domain.Credentials // ключи: ник и email в нижнем регистре
	sessions map[string]storedSession           // ключ: string(tokenHash)
	nextID   int

	createUserCalls    int
	credsCalls         int
	gotUserHash        string
	sessionsCreated    int
	gotTokenHash       []byte
	gotSessionUserID   int
	gotSessionExpires  time.Time
	deleteSessionCalls int
	gotDeletedHash     []byte
	deleteExpiredCalls int
	gotDeleteExpiredAt time.Time

	createUserErr    error
	credsErr         error
	createSessionErr error
	getSessionErr    error
	deleteSessionErr error
	deleteExpiredErr error
}

func newFakeRepo() *fakeAuthRepository {
	return &fakeAuthRepository{
		creds:    map[string]core_domain.Credentials{},
		sessions: map[string]storedSession{},
	}
}

func (f *fakeAuthRepository) put(user core_domain.User, hash string) {
	c := core_domain.NewCredentials(user, hash)
	f.creds[strings.ToLower(user.Username)] = c
	f.creds[strings.ToLower(user.Email)] = c
	if user.ID > f.nextID {
		f.nextID = user.ID
	}
}

// seedUser кладёт в «базу» готового пользователя с настоящим bcrypt-хешем пароля.
func (f *fakeAuthRepository) seedUser(t *testing.T, id int, username, email, password string) core_domain.User {
	t.Helper()
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.MinCost)
	if err != nil {
		t.Fatal(err)
	}
	user := core_domain.NewUser(id, 1, username, email, testNow)
	f.put(user, string(hash))
	return user
}

// seedSession кладёт в «базу» сессию для токена token.
func (f *fakeAuthRepository) seedSession(token string, user core_domain.User, expiresAt time.Time) {
	f.sessions[string(hashToken(token))] = storedSession{
		session: core_domain.NewSession(user.ID, expiresAt),
		user:    user,
	}
}

func (f *fakeAuthRepository) CreateUser(ctx context.Context, user core_domain.User, passwordHash string) (core_domain.User, error) {
	f.createUserCalls++
	if f.createUserErr != nil {
		return core_domain.User{}, f.createUserErr
	}
	_, usernameTaken := f.creds[strings.ToLower(user.Username)]
	_, emailTaken := f.creds[strings.ToLower(user.Email)]
	if usernameTaken || emailTaken {
		return core_domain.User{}, fmt.Errorf("already exists: %w", core_errors.ErrConflict)
	}
	f.nextID++
	created := core_domain.NewUser(f.nextID, 1, user.Username, user.Email, testNow)
	f.gotUserHash = passwordHash
	f.put(created, passwordHash)
	return created, nil
}

func (f *fakeAuthRepository) GetCredentialsByLogin(ctx context.Context, login string) (core_domain.Credentials, error) {
	f.credsCalls++
	if f.credsErr != nil {
		return core_domain.Credentials{}, f.credsErr
	}
	c, ok := f.creds[strings.ToLower(login)]
	if !ok {
		return core_domain.Credentials{}, fmt.Errorf("login %q: %w", login, core_errors.ErrNotFound)
	}
	return c, nil
}

func (f *fakeAuthRepository) CreateSession(ctx context.Context, tokenHash []byte, userID int, expiresAt time.Time) error {
	if f.createSessionErr != nil {
		return f.createSessionErr
	}
	var owner core_domain.User
	found := false
	for _, c := range f.creds {
		if c.User.ID == userID {
			owner, found = c.User, true
			break
		}
	}
	if !found { // как внешний ключ в настоящей БД
		return fmt.Errorf("user %d: %w", userID, core_errors.ErrNotFound)
	}
	f.sessionsCreated++
	f.gotTokenHash = tokenHash
	f.gotSessionUserID = userID
	f.gotSessionExpires = expiresAt
	f.sessions[string(tokenHash)] = storedSession{session: core_domain.NewSession(userID, expiresAt), user: owner}
	return nil
}

func (f *fakeAuthRepository) GetSession(ctx context.Context, tokenHash []byte) (core_domain.Session, core_domain.User, error) {
	if f.getSessionErr != nil {
		return core_domain.Session{}, core_domain.User{}, f.getSessionErr
	}
	st, ok := f.sessions[string(tokenHash)]
	if !ok {
		return core_domain.Session{}, core_domain.User{}, fmt.Errorf("session: %w", core_errors.ErrNotFound)
	}
	return st.session, st.user, nil
}

func (f *fakeAuthRepository) DeleteSession(ctx context.Context, tokenHash []byte) error {
	f.deleteSessionCalls++
	f.gotDeletedHash = tokenHash
	if f.deleteSessionErr != nil {
		return f.deleteSessionErr
	}
	delete(f.sessions, string(tokenHash))
	return nil
}

func (f *fakeAuthRepository) DeleteExpiredSessions(ctx context.Context, now time.Time) error {
	f.deleteExpiredCalls++
	f.gotDeleteExpiredAt = now
	return f.deleteExpiredErr
}

// newTestService собирает сервис с дешёвым bcrypt (иначе тесты идут секунды)
// и замороженными часами.
func newTestService(t *testing.T, repo *fakeAuthRepository) *AuthService {
	t.Helper()
	s, err := NewAuthService(repo, bcrypt.MinCost, testTTL)
	if err != nil {
		t.Fatalf("NewAuthService() failed: %v", err)
	}
	s.now = func() time.Time { return testNow }
	return s
}

// wantSessionFor проверяет, что токен выдан по правилам: 32 байта, в БД лежит только sha256,
// срок — now+TTL, владелец — userID.
func wantSessionFor(t *testing.T, repo *fakeAuthRepository, token string, userID int) {
	t.Helper()
	raw, err := base64.RawURLEncoding.DecodeString(token)
	if err != nil || len(raw) != 32 {
		t.Fatalf("token = %q: want base64url of 32 bytes (decode err %v, len %d)", token, err, len(raw))
	}
	sum := sha256.Sum256([]byte(token))
	if !bytes.Equal(repo.gotTokenHash, sum[:]) {
		t.Error("stored token hash != sha256(token)")
	}
	if bytes.Contains(repo.gotTokenHash, []byte(token)) || string(repo.gotTokenHash) == token {
		t.Error("raw token must never be stored")
	}
	if repo.gotSessionUserID != userID {
		t.Errorf("session user id = %d, want %d", repo.gotSessionUserID, userID)
	}
	if want := testNow.Add(testTTL); !repo.gotSessionExpires.Equal(want) {
		t.Errorf("session expires = %v, want %v", repo.gotSessionExpires, want)
	}
}

func TestNewAuthService(t *testing.T) {
	tests := []struct {
		name    string
		cost    int
		ttl     time.Duration
		wantErr bool
	}{
		{name: "valid", cost: bcrypt.MinCost, ttl: time.Hour},
		{name: "cost below min", cost: bcrypt.MinCost - 1, ttl: time.Hour, wantErr: true},
		{name: "cost above max", cost: bcrypt.MaxCost + 1, ttl: time.Hour, wantErr: true},
		{name: "zero ttl", cost: bcrypt.MinCost, ttl: 0, wantErr: true},
		{name: "negative ttl", cost: bcrypt.MinCost, ttl: -time.Hour, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s, err := NewAuthService(newFakeRepo(), tt.cost, tt.ttl)
			if tt.wantErr {
				if err == nil {
					t.Fatal("NewAuthService() succeeded unexpectedly")
				}
				return
			}
			if err != nil {
				t.Fatalf("NewAuthService() failed: %v", err)
			}
			if cap(s.sem) < 1 {
				t.Errorf("semaphore capacity = %d, want >= 1", cap(s.sem))
			}
		})
	}
}

func TestNewToken(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		token, err := newToken()
		if err != nil {
			t.Fatal(err)
		}
		raw, err := base64.RawURLEncoding.DecodeString(token)
		if err != nil || len(raw) != 32 {
			t.Fatalf("token %q: want base64url of 32 bytes", token)
		}
		if seen[token] {
			t.Fatalf("duplicate token %q", token)
		}
		seen[token] = true
	}
}

func TestHashToken(t *testing.T) {
	a, b := hashToken("token-a"), hashToken("token-a")
	if len(a) != sha256.Size {
		t.Errorf("hash len = %d, want %d", len(a), sha256.Size)
	}
	if !bytes.Equal(a, b) {
		t.Error("hashToken must be deterministic")
	}
	if bytes.Equal(a, hashToken("token-b")) {
		t.Error("different tokens must have different hashes")
	}
}

func TestAuthService_Register_Success(t *testing.T) {
	repo := newFakeRepo()
	s := newTestService(t, repo)

	// лишние пробелы вокруг ника и заглавные буквы в email нормализуются
	user, token, err := s.Register(context.Background(), "  Kant ", "KANT@Mail.ru", "Passw0rd!")
	if err != nil {
		t.Fatalf("Register() failed: %v", err)
	}

	if user.ID == 0 || user.Username != "Kant" || user.Email != "kant@mail.ru" {
		t.Errorf("Register() user = %+v, want ID != 0, Username Kant, Email kant@mail.ru", user)
	}
	if repo.gotUserHash == "Passw0rd!" {
		t.Fatal("password was stored in plain text")
	}
	if err := bcrypt.CompareHashAndPassword([]byte(repo.gotUserHash), []byte("Passw0rd!")); err != nil {
		t.Errorf("stored hash does not match the password: %v", err)
	}
	wantSessionFor(t, repo, token, user.ID)
	if len(s.sem) != 0 {
		t.Errorf("semaphore slots leaked: %d", len(s.sem))
	}
}

func TestAuthService_Register_Invalid(t *testing.T) {
	tests := []struct {
		name     string
		username string
		email    string
		password string
	}{
		{name: "username too short", username: "ab", email: "a@mail.ru", password: "Passw0rd!"},
		{name: "username bad chars", username: "bad name", email: "a@mail.ru", password: "Passw0rd!"},
		{name: "bad email", username: "kant", email: "not-an-email", password: "Passw0rd!"},
		{name: "password too short", username: "kant", email: "a@mail.ru", password: "Pw0rd!"},
		{name: "password cyrillic", username: "kant", email: "a@mail.ru", password: "Пароль1234"},
		{name: "password with space", username: "kant", email: "a@mail.ru", password: "Pass word1"},
		{name: "password equals username", username: "Password1", email: "a@mail.ru", password: "Password1"},
		{name: "password equals username ignoring case", username: "Password1", email: "a@mail.ru", password: "PASSWORD1"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			repo := newFakeRepo()
			s := newTestService(t, repo)

			user, token, err := s.Register(context.Background(), tt.username, tt.email, tt.password)

			if !errors.Is(err, core_errors.ErrInvalidArgument) {
				t.Fatalf("Register() error = %v, want ErrInvalidArgument", err)
			}
			if token != "" || user != (core_domain.User{}) {
				t.Errorf("Register() returned data on error: %+v %q", user, token)
			}
			// дорогие шаги (bcrypt, запись) не должны выполняться для заведомо плохого запроса
			if repo.createUserCalls != 0 || repo.sessionsCreated != 0 {
				t.Errorf("repository was called: users=%d sessions=%d", repo.createUserCalls, repo.sessionsCreated)
			}
		})
	}
}

func TestAuthService_Register_RepositoryErrors(t *testing.T) {
	t.Run("conflict is propagated", func(t *testing.T) {
		repo := newFakeRepo()
		repo.seedUser(t, 1, "Kant", "kant@mail.ru", "Passw0rd!")
		s := newTestService(t, repo)

		_, token, err := s.Register(context.Background(), "Other", "kant@mail.ru", "Passw0rd!")

		if !errors.Is(err, core_errors.ErrConflict) {
			t.Fatalf("Register() error = %v, want ErrConflict", err)
		}
		if token != "" || repo.sessionsCreated != 0 {
			t.Errorf("session must not be created on conflict (token %q, sessions %d)", token, repo.sessionsCreated)
		}
	})

	t.Run("create user error is wrapped", func(t *testing.T) {
		repo := newFakeRepo()
		repo.createUserErr = errBoom
		s := newTestService(t, repo)

		_, _, err := s.Register(context.Background(), "Kant", "kant@mail.ru", "Passw0rd!")

		if !errors.Is(err, errBoom) {
			t.Errorf("Register() error = %v, want wrapped %v", err, errBoom)
		}
	})

	t.Run("create session error", func(t *testing.T) {
		repo := newFakeRepo()
		repo.createSessionErr = errBoom
		s := newTestService(t, repo)

		_, token, err := s.Register(context.Background(), "Kant", "kant@mail.ru", "Passw0rd!")

		if !errors.Is(err, errBoom) {
			t.Errorf("Register() error = %v, want wrapped %v", err, errBoom)
		}
		if token != "" {
			t.Errorf("token = %q, want empty", token)
		}
		if repo.createUserCalls != 1 { // пользователь создан, войти он сможет обычным логином
			t.Errorf("CreateUser calls = %d, want 1", repo.createUserCalls)
		}
	})
}

func TestAuthService_Login_Success(t *testing.T) {
	tests := []struct {
		name  string
		login string
	}{
		{name: "by username", login: "Kant"},
		{name: "username in other case", login: "kAnT"},
		{name: "username with spaces", login: "  Kant  "},
		{name: "by email", login: "kant@mail.ru"},
		{name: "email in other case", login: "KANT@Mail.RU"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			repo := newFakeRepo()
			seeded := repo.seedUser(t, 7, "Kant", "kant@mail.ru", "Passw0rd!")
			s := newTestService(t, repo)

			user, token, err := s.Login(context.Background(), tt.login, "Passw0rd!")

			if err != nil {
				t.Fatalf("Login() failed: %v", err)
			}
			if user != seeded {
				t.Errorf("Login() user = %+v, want %+v", user, seeded)
			}
			wantSessionFor(t, repo, token, seeded.ID)
			if repo.deleteExpiredCalls != 1 || !repo.gotDeleteExpiredAt.Equal(testNow) {
				t.Errorf("DeleteExpiredSessions calls = %d at %v, want 1 call at %v",
					repo.deleteExpiredCalls, repo.gotDeleteExpiredAt, testNow)
			}
			if len(s.sem) != 0 {
				t.Errorf("semaphore slots leaked: %d", len(s.sem))
			}
		})
	}
}

// Все причины отказа должны давать ОДНУ И ТУ ЖЕ ошибку: по ответу нельзя понять,
// существует ли такой пользователь.
func TestAuthService_Login_Unauthorized(t *testing.T) {
	tests := []struct {
		name      string
		login     string
		password  string
		skipsRepo bool // заведомо неверный ввод отсекается до базы и bcrypt: не тратим ресурсы
	}{
		{name: "unknown login", login: "nobody", password: "Passw0rd!"},
		{name: "wrong password", login: "Kant", password: "WrongPass1!"},
		{name: "empty password", login: "Kant", password: ""},
		{name: "password with different case", login: "Kant", password: "passw0rd!"},
		{name: "login too long", login: strings.Repeat("a", 255), password: "Passw0rd!", skipsRepo: true},
		{name: "password too long", login: "Kant", password: strings.Repeat("a", core_domain.MaxPasswordLen+1), skipsRepo: true},
		{name: "password exactly at the limit is still checked", login: "Kant", password: strings.Repeat("a", core_domain.MaxPasswordLen)},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			repo := newFakeRepo()
			repo.seedUser(t, 7, "Kant", "kant@mail.ru", "Passw0rd!")
			s := newTestService(t, repo)

			user, token, err := s.Login(context.Background(), tt.login, tt.password)

			if !errors.Is(err, core_errors.ErrUnauthorized) {
				t.Fatalf("Login() error = %v, want ErrUnauthorized", err)
			}
			if err.Error() != errInvalidCredentials.Error() {
				t.Errorf("Login() error text = %q, want the same text for every reason: %q",
					err.Error(), errInvalidCredentials.Error())
			}
			if token != "" || user != (core_domain.User{}) {
				t.Errorf("Login() returned data on error: %+v %q", user, token)
			}
			if repo.sessionsCreated != 0 {
				t.Errorf("sessions created = %d, want 0", repo.sessionsCreated)
			}
			if tt.skipsRepo != (repo.credsCalls == 0) {
				t.Errorf("GetCredentialsByLogin calls = %d, skipsRepo = %v", repo.credsCalls, tt.skipsRepo)
			}
			if len(s.sem) != 0 {
				t.Errorf("semaphore slots leaked: %d", len(s.sem))
			}
		})
	}
}

func TestAuthService_Login_RepositoryErrors(t *testing.T) {
	t.Run("credentials error is a server error, not 401", func(t *testing.T) {
		repo := newFakeRepo()
		repo.credsErr = errBoom
		s := newTestService(t, repo)

		_, _, err := s.Login(context.Background(), "Kant", "Passw0rd!")

		if !errors.Is(err, errBoom) {
			t.Errorf("Login() error = %v, want wrapped %v", err, errBoom)
		}
		if errors.Is(err, core_errors.ErrUnauthorized) {
			t.Error("a database failure must not look like 'wrong password'")
		}
	})

	t.Run("cleanup failure does not break login", func(t *testing.T) {
		repo := newFakeRepo()
		repo.seedUser(t, 7, "Kant", "kant@mail.ru", "Passw0rd!")
		repo.deleteExpiredErr = errBoom
		s := newTestService(t, repo)

		_, token, err := s.Login(context.Background(), "Kant", "Passw0rd!")

		if err != nil || token == "" {
			t.Errorf("Login() = %q, %v; want a token and no error", token, err)
		}
	})

	t.Run("create session error", func(t *testing.T) {
		repo := newFakeRepo()
		repo.seedUser(t, 7, "Kant", "kant@mail.ru", "Passw0rd!")
		repo.createSessionErr = errBoom
		s := newTestService(t, repo)

		_, token, err := s.Login(context.Background(), "Kant", "Passw0rd!")

		if !errors.Is(err, errBoom) {
			t.Errorf("Login() error = %v, want wrapped %v", err, errBoom)
		}
		if token != "" {
			t.Errorf("token = %q, want empty", token)
		}
	})
}

func TestAuthService_Login_NewTokenEachTime(t *testing.T) {
	repo := newFakeRepo()
	repo.seedUser(t, 7, "Kant", "kant@mail.ru", "Passw0rd!")
	s := newTestService(t, repo)

	_, first, err1 := s.Login(context.Background(), "Kant", "Passw0rd!")
	_, second, err2 := s.Login(context.Background(), "Kant", "Passw0rd!")

	if err1 != nil || err2 != nil {
		t.Fatalf("Login() failed: %v, %v", err1, err2)
	}
	if first == second {
		t.Error("every login must issue a new token")
	}
	if len(repo.sessions) != 2 { // вход с двух устройств: обе сессии живы
		t.Errorf("sessions = %d, want 2", len(repo.sessions))
	}
}

// Когда все слоты bcrypt заняты, запрос ждёт, а при отмене контекста выходит, а не виснет.
func TestAuthService_BcryptQueueRespectsContext(t *testing.T) {
	fillQueue := func(s *AuthService) {
		for i := 0; i < cap(s.sem); i++ {
			s.sem <- struct{}{}
		}
	}
	cancelled := func() context.Context {
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		return ctx
	}

	t.Run("login", func(t *testing.T) {
		repo := newFakeRepo()
		repo.seedUser(t, 7, "Kant", "kant@mail.ru", "Passw0rd!")
		s := newTestService(t, repo)
		fillQueue(s)

		_, _, err := s.Login(cancelled(), "Kant", "Passw0rd!")

		if !errors.Is(err, context.Canceled) {
			t.Errorf("Login() error = %v, want context.Canceled", err)
		}
		if errors.Is(err, core_errors.ErrUnauthorized) {
			t.Error("cancellation must not look like 'wrong password'")
		}
	})

	t.Run("register", func(t *testing.T) {
		repo := newFakeRepo()
		s := newTestService(t, repo)
		fillQueue(s)

		_, _, err := s.Register(cancelled(), "Kant", "kant@mail.ru", "Passw0rd!")

		if !errors.Is(err, context.Canceled) {
			t.Errorf("Register() error = %v, want context.Canceled", err)
		}
		if repo.createUserCalls != 0 {
			t.Errorf("CreateUser calls = %d, want 0", repo.createUserCalls)
		}
	})
}

func TestAuthService_Authenticate(t *testing.T) {
	user := core_domain.NewUser(7, 1, "Kant", "kant@mail.ru", testNow)

	tests := []struct {
		name      string
		token     string
		expiresAt time.Time // сессия с токеном "good"; нулевое — сессии нет
		repoErr   error
		wantErr   error // nil — успех
		notErr    error // ошибка, на которую результат НЕ должен быть похож
	}{
		{name: "valid", token: "good", expiresAt: testNow.Add(time.Hour)},
		{name: "valid for a long time", token: "good", expiresAt: testNow.Add(testTTL)},
		{name: "one second left", token: "good", expiresAt: testNow.Add(time.Second)},
		{name: "expired a second ago", token: "good", expiresAt: testNow.Add(-time.Second), wantErr: core_errors.ErrUnauthorized},
		{name: "expires exactly now", token: "good", expiresAt: testNow, wantErr: core_errors.ErrUnauthorized},
		{name: "unknown token", token: "other", expiresAt: testNow.Add(time.Hour), wantErr: core_errors.ErrUnauthorized},
		{name: "no session at all", token: "good", wantErr: core_errors.ErrUnauthorized},
		{name: "empty token", token: "", expiresAt: testNow.Add(time.Hour), wantErr: core_errors.ErrUnauthorized},
		{name: "repository error is a server error", token: "good", expiresAt: testNow.Add(time.Hour),
			repoErr: errBoom, wantErr: errBoom, notErr: core_errors.ErrUnauthorized},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			repo := newFakeRepo()
			repo.getSessionErr = tt.repoErr
			if !tt.expiresAt.IsZero() {
				repo.seedSession("good", user, tt.expiresAt)
			}
			s := newTestService(t, repo)

			got, err := s.Authenticate(context.Background(), tt.token)

			if tt.wantErr != nil {
				if !errors.Is(err, tt.wantErr) {
					t.Fatalf("Authenticate() error = %v, want wrapped %v", err, tt.wantErr)
				}
				if tt.notErr != nil && errors.Is(err, tt.notErr) {
					t.Errorf("Authenticate() error = %v, must not be %v", err, tt.notErr)
				}
				if got != (core_domain.User{}) {
					t.Errorf("Authenticate() returned user on error: %+v", got)
				}
				return
			}
			if err != nil {
				t.Fatalf("Authenticate() failed: %v", err)
			}
			if got != user {
				t.Errorf("Authenticate() = %+v, want %+v", got, user)
			}
		})
	}
}

func TestAuthService_Logout(t *testing.T) {
	user := core_domain.NewUser(7, 1, "Kant", "kant@mail.ru", testNow)

	t.Run("removes the session by token hash", func(t *testing.T) {
		repo := newFakeRepo()
		repo.seedSession("good", user, testNow.Add(time.Hour))
		s := newTestService(t, repo)

		if err := s.Logout(context.Background(), "good"); err != nil {
			t.Fatalf("Logout() failed: %v", err)
		}

		if !bytes.Equal(repo.gotDeletedHash, hashToken("good")) {
			t.Error("Logout() must delete by sha256(token), not by the raw token")
		}
		if _, err := s.Authenticate(context.Background(), "good"); !errors.Is(err, core_errors.ErrUnauthorized) {
			t.Errorf("Authenticate() after Logout error = %v, want ErrUnauthorized", err)
		}
	})

	t.Run("unknown token is not an error", func(t *testing.T) {
		s := newTestService(t, newFakeRepo())

		if err := s.Logout(context.Background(), "nothing"); err != nil {
			t.Errorf("Logout() = %v, want nil (logout is idempotent)", err)
		}
	})

	t.Run("empty token does not touch the repository", func(t *testing.T) {
		repo := newFakeRepo()
		s := newTestService(t, repo)

		if err := s.Logout(context.Background(), ""); err != nil {
			t.Errorf("Logout() = %v, want nil", err)
		}
		if repo.deleteSessionCalls != 0 {
			t.Errorf("DeleteSession calls = %d, want 0", repo.deleteSessionCalls)
		}
	})

	t.Run("repository error is wrapped", func(t *testing.T) {
		repo := newFakeRepo()
		repo.deleteSessionErr = errBoom
		s := newTestService(t, repo)

		if err := s.Logout(context.Background(), "good"); !errors.Is(err, errBoom) {
			t.Errorf("Logout() error = %v, want wrapped %v", err, errBoom)
		}
	})
}
