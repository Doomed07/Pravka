package reviews_repository_postgres

// Интеграционный тест: нужна настоящая PostgreSQL с применёнными миграциями.
// Запуск: PRAVKI_TEST_DB=1 POSTGRES_HOST=... POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=... POSTGRES_TIMEOUT=5s go test ./...
// Без PRAVKI_TEST_DB тест пропускается.

import (
	"context"
	"errors"
	"os"
	"testing"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pgx "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool/pgx"
)

func TestReviewsRepository_Integration(t *testing.T) {
	if os.Getenv("PRAVKI_TEST_DB") == "" {
		t.Skip("PRAVKI_TEST_DB не задан: нужна настоящая PostgreSQL")
	}
	ctx := context.Background()
	pool, err := core_postgres_pgx.NewConnPool(core_postgres_pgx.NewConfigMust(), ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	var u1, u2 int
	for i, name := range []string{"repo_test_a", "repo_test_b"} {
		_, _ = pool.Exec(ctx, `DELETE FROM pravkiapp.users WHERE username = $1`, name)
		var id int
		if err := pool.QueryRow(ctx, `INSERT INTO pravkiapp.users (username, email, password_hash) VALUES ($1, $2, $3) RETURNING id`,
			name, name+"@example.com", "$2a$12$abcdefghijklmnopqrstuuabcdefghijklmnopqrstuvwxyz01234").Scan(&id); err != nil {
			t.Fatalf("create user %d: %v", i, err)
		}
		if i == 0 {
			u1 = id
		} else {
			u2 = id
		}
	}
	repo := NewReviewsRepository(pool)

	saved, err := repo.CreateReview(ctx, core_domain.ContractReview{
		UserID: u1, TheirsName: "Договор 03.04.docx", Playbook: "private/s.yaml", PlaybookName: "Услуги", OurRole: "Заказчик",
		Counts: map[string]int{"всего": 30, "красные линии": 2}, Warnings: []string{"Найдено правок без отметки: 3"},
	}, core_domain.ReviewFiles{ReportHTML: []byte("<h1>Отчёт</h1>"), ReportXLSX: []byte("PK\x03\x04"), Changes: []byte(`[{"id":"E001"}]`),
		Document: []byte(`[{"index":0}]`), Unified: []byte("PKdocx")})
	if err != nil {
		t.Fatal(err)
	}
	if saved.ID == 0 || saved.Counts["красные линии"] != 2 || len(saved.Warnings) != 1 || saved.CreatedAt.IsZero() {
		t.Fatalf("saved = %+v", saved)
	}

	list, err := repo.ListReviews(ctx, u1, 10, 0)
	if err != nil || len(list) != 1 || list[0].TheirsName != "Договор 03.04.docx" {
		t.Fatalf("list = %+v, err = %v", list, err)
	}
	if other, _ := repo.ListReviews(ctx, u2, 10, 0); len(other) != 0 {
		t.Fatalf("user 2 sees user 1 reviews: %+v", other)
	}
	if _, err := repo.GetReview(ctx, u2, saved.ID); !errors.Is(err, core_errors.ErrNotFound) {
		t.Fatalf("other user's review: err = %v, want not found", err)
	}
	for kind, want := range map[string]string{"html": "<h1>Отчёт</h1>", "xlsx": "PK\x03\x04", "changes": `[{"id": "E001"}]`,
		"document": `[{"index": 0}]`, "docx": "PKdocx"} {
		got, err := repo.GetFile(ctx, u1, saved.ID, kind)
		if err != nil || string(got) != want {
			t.Errorf("file %s = %q, err = %v", kind, got, err)
		}
	}
	if _, err := repo.GetFile(ctx, u2, saved.ID, "html"); !errors.Is(err, core_errors.ErrNotFound) {
		t.Errorf("other user's report: err = %v", err)
	}
	if err := repo.DeleteReview(ctx, u2, saved.ID); !errors.Is(err, core_errors.ErrNotFound) {
		t.Errorf("other user deleted the review: err = %v", err)
	}
	if err := repo.DeleteReview(ctx, u1, saved.ID); err != nil {
		t.Fatal(err)
	}
	_, _ = pool.Exec(ctx, `DELETE FROM pravkiapp.users WHERE id IN ($1, $2)`, u1, u2)
}
