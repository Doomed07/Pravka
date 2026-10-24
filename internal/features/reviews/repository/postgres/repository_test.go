package reviews_repository_postgres

// Интеграционный тест: нужна настоящая PostgreSQL с применёнными миграциями.
// Запуск: PRAVKI_TEST_DB=1 POSTGRES_HOST=... POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=... POSTGRES_TIMEOUT=5s go test ./...
// Без PRAVKI_TEST_DB тест пропускается.

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_postgres_pool "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool"
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

// «Как решали раньше»: подсказка — только из прошлых разборов того же юриста, того же типа договора и той же нашей роли;
// та же правка, записанная иначе («30» → «10» и «30 календарных дней» → «10 календарных дней»), — первой.
func TestReviewsRepository_Precedents(t *testing.T) {
	if os.Getenv("PRAVKI_TEST_DB") == "" {
		t.Skip("PRAVKI_TEST_DB не задан: нужна настоящая PostgreSQL")
	}
	ctx := context.Background()
	pool, err := core_postgres_pgx.NewConnPool(core_postgres_pgx.NewConfigMust(), ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	users := map[string]int{}
	for _, name := range []string{"prec_test_a", "prec_test_b"} {
		_, _ = pool.Exec(ctx, `DELETE FROM pravkiapp.users WHERE username = $1`, name)
		var id int
		if err := pool.QueryRow(ctx, `INSERT INTO pravkiapp.users (username, email, password_hash) VALUES ($1, $2, $3) RETURNING id`,
			name, name+"@example.com", "$2a$12$abcdefghijklmnopqrstuuabcdefghijklmnopqrstuvwxyz01234").Scan(&id); err != nil {
			t.Fatal(err)
		}
		users[name] = id
	}
	defer func() { _, _ = pool.Exec(ctx, `DELETE FROM pravkiapp.users WHERE username LIKE 'prec_test_%'`) }()
	a, b := users["prec_test_a"], users["prec_test_b"]
	repo := NewReviewsRepository(pool)

	const ship = `Поставщик поставляет Товар в течение 30 календарных дней с даты получения аванса.`
	const pen = `За просрочку поставки Поставщик уплачивает неустойку 0,1% от стоимости непоставленного Товара за каждый день.`
	const court = `Споры рассматриваются в Арбитражном суде города Москвы.`
	change := func(id, topic, before, after, context string) string {
		return fmt.Sprintf(`{"id":%q,"kind":"replace","topic":%q,"before":%q,"after":%q,"context":%q}`, id, topic, before, after, context)
	}
	review := func(user int, typ, role, name string, changes ...string) int {
		t.Helper()
		rev, err := repo.CreateReview(ctx, core_domain.ContractReview{UserID: user, TheirsName: name, OurRole: role, ContractType: typ},
			core_domain.ReviewFiles{ReportHTML: []byte("-"), ReportXLSX: []byte("-"), Changes: []byte("[" + strings.Join(changes, ",") + "]")})
		if err != nil {
			t.Fatal(err)
		}
		return rev.ID
	}
	choose := func(user, id int, change, choice, text string) {
		t.Helper()
		if err := repo.SaveChoice(ctx, user, id, core_domain.ReviewChoice{ChangeID: change, Choice: choice, Text: text}); err != nil {
			t.Fatal(err)
		}
	}

	// прошлые разборы юриста A: поставка, мы — Поставщик
	r1 := review(a, "supply", "Поставщик", "Поставка_ООО_Альфа.docx",
		change("E001", "сроки исполнения", "30 календарных дней", "10 календарных дней", ship),
		change("E002", "неустойка и штрафы", "0,1%", "0,5%", pen),
		change("E003", "разрешение споров", "Москвы", "Казани", court))
	choose(a, r1, "E001", "counter", "в течение 20 календарных дней")
	choose(a, r1, "E002", "reject", "")
	choose(a, r1, "E003", "reply", "Согласуем позже") // ответ на комментарий — не решение по правке
	r2 := review(a, "supply", "Поставщик", "Поставка_ООО_Бета.docx",
		change("E001", "сроки исполнения", "30 календарных дней", "45 календарных дней", ship))
	choose(a, r2, "E001", "accept", "")
	// та же правка в другом абзаце (абзац похож меньше) — выше похожей правки в том же абзаце
	r3 := review(a, "supply", "Поставщик", "Поставка_ООО_Дельта.docx",
		change("E001", "сроки исполнения", "30 календарных дней", "10 календарных рабочих дней", ship))
	choose(a, r3, "E001", "reject", "")
	r4 := review(a, "supply", "Поставщик", "Поставка_ООО_Эпсилон.docx",
		change("E001", "сроки исполнения", "30", "10", `Товар поставляется партиями в течение 30 календарных дней с даты подписания спецификации.`))
	choose(a, r4, "E001", "reject", "")
	// та же правка, но мы — Покупатель, договор услуг или другой юрист: не подсказка
	for _, x := range []struct {
		user      int
		typ, role string
	}{{a, "supply", "Покупатель"}, {a, "services", "Поставщик"}, {b, "supply", "Поставщик"}} {
		id := review(x.user, x.typ, x.role, "чужое.docx", change("E001", "сроки исполнения", "30", "10", ship))
		choose(x.user, id, "E001", "reject", "")
	}

	// новый разбор: правки найдены сравнением редакций — записаны короче
	cur := review(a, "supply", "Поставщик", "Поставка_ООО_Гамма.docx",
		change("S001", "сроки исполнения", "30", "10", ship),
		change("S002", "разрешение споров", "Москвы", "Казани", court),
		change("S003", "прочее", "Товар", "Продукция", `Наименование и количество Товара указываются в спецификации.`),
		// та же суть {+10, -30}, что и в сроке поставки, но это аванс: другая тема — не подсказка
		change("S004", "порядок и сроки оплаты", "30%", "10%",
			`Покупатель вносит аванс в размере 30% от стоимости Товара в течение 5 рабочих дней с даты подписания договора.`),
		// та же суть и тема, но абзац о другом (монтаж, а не поставка): похожая правка, а не «та же»
		change("S005", "сроки исполнения", "30", "10", `Монтаж оборудования выполняется Поставщиком в течение 30 календарных дней.`),
		// та же неустойка 0,1% → 0,5%, но платит Покупатель, а в прошлом разборе — Поставщик: не подсказка
		change("S006", "неустойка и штрафы", "0,1%", "0,5%",
			`За просрочку оплаты Покупатель уплачивает неустойку 0,1% от стоимости неоплаченного Товара за каждый день.`))
	choose(a, cur, "S001", "reject", "") // решение по самому разбору — не «как решали раньше»

	got, err := repo.ListPrecedents(ctx, a, cur)
	if err != nil {
		t.Fatal(err)
	}
	by := map[string][]core_domain.Precedent{}
	for _, p := range got {
		by[p.ChangeID] = append(by[p.ChangeID], p)
	}
	s1 := by["S001"]
	if len(s1) == 0 || s1[0].ReviewID != r1 || !s1[0].Same || s1[0].Choice != "counter" || s1[0].Text != "в течение 20 календарных дней" ||
		s1[0].PastChangeID != "E001" || s1[0].TheirsName != "Поставка_ООО_Альфа.docx" {
		t.Fatalf("S001: same edit first, from our own role and type only: %+v", s1)
	}
	if len(s1) != core_domain.MaxPrecedents || s1[1].ReviewID != r4 || !s1[1].Same || s1[2].ReviewID != r3 || s1[2].Same {
		t.Fatalf("S001: the same edit in another clause goes before a similar one, at most %d hints: %+v", core_domain.MaxPrecedents, s1)
	}
	if s5 := by["S005"]; len(s5) == 0 || s5[0].Same {
		t.Fatalf("S005: another paragraph is a similar edit, not the same: %+v", s5)
	}
	for _, id := range []string{"S002", "S003", "S004", "S006"} {
		if len(by[id]) != 0 {
			t.Fatalf("%s: no decision, nothing similar, another topic or another obligor → no hint: %+v", id, by[id])
		}
	}
	if _, err := repo.ListPrecedents(ctx, b, cur); !errors.Is(err, core_errors.ErrNotFound) {
		t.Fatalf("other user's review: err = %v", err)
	}
	// договор аренды: подсказок нет (работаем только с поставкой и услугами)
	pastLease := review(a, "lease", "Поставщик", "Аренда_прошлая.docx", change("E001", "сроки исполнения", "30", "10", ship))
	choose(a, pastLease, "E001", "reject", "")
	lease := review(a, "lease", "Поставщик", "Аренда.docx", change("E001", "сроки исполнения", "30", "10", ship))
	if got, err := repo.ListPrecedents(ctx, a, lease); err != nil || len(got) != 0 {
		t.Fatalf("lease: %+v, err = %v", got, err)
	}
}

// «Что говорит ГК»: векторы — только для правок с темами, к которым подсказывается ГК; подсказки — только из частей
// кодекса для типа договора и не дальше порога.
func TestReviewsRepository_LawHints(t *testing.T) {
	if os.Getenv("PRAVKI_TEST_DB") == "" {
		t.Skip("PRAVKI_TEST_DB не задан: нужна настоящая PostgreSQL")
	}
	ctx := context.Background()
	pool, err := core_postgres_pgx.NewConnPool(core_postgres_pgx.NewConfigMust(), ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	_, _ = pool.Exec(ctx, `DELETE FROM pravkiapp.users WHERE username = 'law_test'`)
	var user int
	if err := pool.QueryRow(ctx, `INSERT INTO pravkiapp.users (username, email, password_hash) VALUES ('law_test', 'law_test@example.com', $1)
	RETURNING id`, "$2a$12$abcdefghijklmnopqrstuuabcdefghijklmnopqrstuvwxyz01234").Scan(&user); err != nil {
		t.Fatal(err)
	}
	defer func() { _, _ = pool.Exec(ctx, `DELETE FROM pravkiapp.users WHERE id = $1`, user) }()

	axis := func(i int) []float32 { // единичный вектор: расстояние 0 до себя, 1 до другого
		v := make([]float32, 1024)
		v[i] = 1
		return v
	}
	_, _ = pool.Exec(ctx, `DELETE FROM pravkiapp.law_points WHERE code = 'ГК РФ' AND title LIKE 'тест %'`)
	defer func() {
		_, _ = pool.Exec(ctx, `DELETE FROM pravkiapp.law_points WHERE code = 'ГК РФ' AND title LIKE 'тест %'`)
	}()
	for _, p := range []struct {
		article string
		axis    int
	}{{"511", 0}, {"782", 0}, {"1225", 0}, {"330", 1}, {"314", 0}} {
		if _, err := pool.Exec(ctx, `INSERT INTO pravkiapp.law_points (code, article, seq, point, title, text, embedding)
		VALUES ('ГК РФ', $1, 900, '1', $2, 'текст', $3::vector)`, p.article, "тест "+p.article, vectorLiteral(axis(p.axis))); err != nil {
			t.Fatal(err)
		}
	}
	repo := NewReviewsRepository(pool)
	changes := `[{"id":"E001","kind":"replace","topic":"сроки исполнения","context":"30 дней","context_after":"10 дней"},
	{"id":"E002","kind":"replace","topic":"налоги","context":"НДС 20%","context_after":"НДС 0%"},
	{"id":"E003","kind":"comment","topic":"сроки исполнения","after":"Просим"},
	{"id":"E004","kind":"replace","topic":"","context":"собственность","context_after":"собсвенность"},
	{"id":"E005","kind":"replace","topic":"сроки исполнения","materiality":"техническая","context":"дней,","context_after":"дней"}]`
	review := func(typ string) int {
		rev, err := repo.CreateReview(ctx, core_domain.ContractReview{UserID: user, TheirsName: "x.docx", ContractType: typ},
			core_domain.ReviewFiles{ReportHTML: []byte("-"), ReportXLSX: []byte("-"), Changes: []byte(changes)})
		if err != nil {
			t.Fatal(err)
		}
		return rev.ID
	}
	supply := review("supply")
	missing, err := repo.ChangesWithoutVectors(ctx, user, supply)
	ids := []string{}
	for _, m := range missing {
		ids = append(ids, m.ID)
	}
	if err != nil || strings.Join(ids, ",") != "E001,E002,E004" || missing[0].ContextAfter != "10 дней" {
		t.Fatalf("vectors for all edits except comments and technical ones: %v, err = %v", ids, err)
	}
	vecs := map[string][]float32{}
	for _, id := range ids {
		vecs[id] = axis(0)
	}
	if err := repo.SaveVectors(ctx, supply, "bge-m3", vecs); err != nil {
		t.Fatal(err)
	}
	if again, _ := repo.ChangesWithoutVectors(ctx, user, supply); len(again) != 0 {
		t.Fatalf("vector saved, nothing left: %+v", again)
	}
	hints, err := repo.ListLawHints(ctx, user, supply)
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, h := range hints {
		if h.ChangeID != "E001" {
			t.Fatalf("taxes and edits without a topic get no law hints: %+v", h)
		}
		if strings.HasPrefix(h.Title, "тест ") {
			got = append(got, h.Article)
		}
	}
	// 782 (услуги) и 1225 (часть четвёртая) — не для поставки; 330 — дальше порога
	if strings.Join(got, ",") != "511,314" && strings.Join(got, ",") != "314,511" {
		t.Fatalf("supply hints: %v (all: %+v)", got, hints)
	}
	if _, err := repo.ListLawHints(ctx, user+100000, supply); !errors.Is(err, core_errors.ErrNotFound) {
		t.Fatalf("other user's review: err = %v", err)
	}
	if m, _ := repo.ChangesWithoutVectors(ctx, user, review("lease")); len(m) != 0 {
		t.Fatalf("lease: no law hints: %+v", m)
	}
}

// testUser — пользователь для интеграционного теста; удаляется вместе со всеми разборами после теста.
func testUser(t *testing.T, ctx context.Context, pool interface {
	Exec(context.Context, string, ...any) (core_postgres_pool.CommandTag, error)
	QueryRow(context.Context, string, ...any) core_postgres_pool.Row
}, name string) int {
	t.Helper()
	_, _ = pool.Exec(ctx, `DELETE FROM pravkiapp.users WHERE username = $1`, name)
	var id int
	if err := pool.QueryRow(ctx, `INSERT INTO pravkiapp.users (username, email, password_hash) VALUES ($1, $2, $3) RETURNING id`,
		name, name+"@example.com", "$2a$12$abcdefghijklmnopqrstuuabcdefghijklmnopqrstuvwxyz01234").Scan(&id); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = pool.Exec(context.Background(), `DELETE FROM pravkiapp.users WHERE id = $1`, id) })
	return id
}

// near — единичный вектор по оси i с небольшим отклонением k по оси 1023: расстояние до axis(i) около 0,005·k².
func near(i int, k float32) []float32 {
	v := make([]float32, 1024)
	v[i], v[1023] = 1, 0.1*k
	return v
}

// «Ваши прошлые формулировки»: другой текст того же пункта из прошлой редакции — да; тот же шаблон, другая обязанная
// сторона, далёкий по смыслу абзац, чужая роль — нет; одинаковый текст из двух разборов — один раз.
func TestReviewsRepository_Wordings(t *testing.T) {
	if os.Getenv("PRAVKI_TEST_DB") == "" {
		t.Skip("PRAVKI_TEST_DB не задан: нужна настоящая PostgreSQL")
	}
	ctx := context.Background()
	pool, err := core_postgres_pgx.NewConnPool(core_postgres_pgx.NewConfigMust(), ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	user := testUser(t, ctx, pool, "wording_test")
	repo := NewReviewsRepository(pool)
	review := func(role, changes string) int {
		rev, err := repo.CreateReview(ctx, core_domain.ContractReview{UserID: user, TheirsName: role + ".docx", OurRole: role,
			ContractType: "supply"}, core_domain.ReviewFiles{ReportHTML: []byte("-"), ReportXLSX: []byte("-"), Changes: []byte(changes)})
		if err != nil {
			t.Fatal(err)
		}
		return rev.ID
	}
	const ours = "Поставщик поставляет Товар в течение 30 календарных дней с даты получения аванса."
	const other = "Срок поставки Товара Поставщиком — не позднее 45 рабочих дней после поступления предоплаты."
	save := func(id int, paras []core_domain.DocParagraph, vecs [][]float32) {
		t.Helper()
		if err := repo.SaveParagraphs(ctx, id, "bge-m3", paras, vecs); err != nil {
			t.Fatal(err)
		}
	}
	past := review("Поставщик", "[]")
	save(past, []core_domain.DocParagraph{
		{Index: 1, Clause: "3.1", Text: other},
		{Index: 2, Clause: "3.1", Text: ours}, // тот же шаблон
		{Index: 3, Clause: "3.2", Text: "Покупатель принимает Товар в течение 30 календарных дней с даты поставки."},
		{Index: 4, Clause: "8.1", Text: "Споры разрешаются в Арбитражном суде города Москвы, претензионный порядок обязателен."},
	}, [][]float32{near(0, 1), near(0, 0), near(0, 0), near(1, 0)})
	past2 := review("Поставщик", "[]")
	save(past2, []core_domain.DocParagraph{{Index: 1, Clause: "3.1", Text: other}}, [][]float32{near(0, 2)})
	buyer := review("Покупатель", "[]") // мы — Покупатель: не наша формулировка для роли Поставщика
	save(buyer, []core_domain.DocParagraph{{Index: 1, Clause: "3.1", Text: "Поставщик передаёт Товар в течение 10 дней."}},
		[][]float32{near(0, 0)})

	cur := review("Поставщик", `[{"id":"E001","kind":"replace","topic":"сроки исполнения","paragraph_index":7},
	{"id":"E002","kind":"comment","topic":"сроки исполнения","paragraph_index":7},
	{"id":"E003","kind":"replace","topic":"сроки исполнения","materiality":"техническая","paragraph_index":7}]`)
	save(cur, []core_domain.DocParagraph{{Index: 7, Clause: "3.1", Text: ours}}, [][]float32{near(0, 0)})

	got, err := repo.ListWordings(ctx, user, cur)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].ChangeID != "E001" || got[0].Text != other || got[0].ReviewID != past {
		t.Fatalf("one different wording of the same clause, once: %+v", got)
	}
	if _, err := repo.ListWordings(ctx, user+100000, cur); !errors.Is(err, core_errors.ErrNotFound) {
		t.Fatalf("other user's review: err = %v", err)
	}
}

// «Как решали раньше» по смыслу: только близкие по вектору прошлые решения той же темы, стороны, типа и роли и только
// к правкам без подсказок по словам.
func TestReviewsRepository_SemanticPrecedents(t *testing.T) {
	if os.Getenv("PRAVKI_TEST_DB") == "" {
		t.Skip("PRAVKI_TEST_DB не задан: нужна настоящая PostgreSQL")
	}
	ctx := context.Background()
	pool, err := core_postgres_pgx.NewConnPool(core_postgres_pgx.NewConfigMust(), ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	user := testUser(t, ctx, pool, "semantic_test")
	repo := NewReviewsRepository(pool)
	ch := func(id, topic, para string) string {
		return fmt.Sprintf(`{"id":%q,"kind":"replace","topic":%q,"before":"a","after":"b","context_after":%q}`, id, topic, para)
	}
	review := func(role, typ string, changes ...string) int {
		rev, err := repo.CreateReview(ctx, core_domain.ContractReview{UserID: user, TheirsName: "п.docx", OurRole: role, ContractType: typ},
			core_domain.ReviewFiles{ReportHTML: []byte("-"), ReportXLSX: []byte("-"), Changes: []byte("[" + strings.Join(changes, ",") + "]")})
		if err != nil {
			t.Fatal(err)
		}
		return rev.ID
	}
	decide := func(id int, vecs map[string][]float32, choices map[string]string) {
		t.Helper()
		if err := repo.SaveVectors(ctx, id, "bge-m3", vecs); err != nil {
			t.Fatal(err)
		}
		for c, choice := range choices {
			text := ""
			if choice == "counter" {
				text = "в течение 20 дней"
			}
			if err := repo.SaveChoice(ctx, user, id, core_domain.ReviewChoice{ChangeID: c, Choice: choice, Text: text}); err != nil {
				t.Fatal(err)
			}
		}
	}
	const supplier = "Поставщик передаёт Товар в течение 20 дней с даты оплаты."
	past := review("Поставщик", "supply",
		ch("E001", "сроки исполнения", supplier),
		ch("E002", "неустойка и штрафы", supplier),                                     // другая тема
		ch("E003", "сроки исполнения", "Покупатель принимает Товар в течение 5 дней."), // другая обязанная сторона
		ch("E004", "сроки исполнения", supplier),                                       // далеко по смыслу
		ch("E005", "сроки исполнения", supplier))                                       // без решения юриста
	decide(past, map[string][]float32{"E001": near(0, 1), "E002": near(0, 0), "E003": near(0, 0), "E004": near(2, 0),
		"E005": near(0, 0)}, map[string]string{"E001": "counter", "E002": "reject", "E003": "accept", "E004": "reject"})
	buyer := review("Покупатель", "supply", ch("E001", "сроки исполнения", supplier))
	decide(buyer, map[string][]float32{"E001": near(0, 0)}, map[string]string{"E001": "reject"})

	cur := review("Поставщик", "supply",
		ch("S001", "сроки исполнения", "Поставщик поставляет Товар не позднее 10 дней после аванса."),
		ch("S002", "сроки исполнения", "Поставщик поставляет Товар не позднее 10 дней после аванса."))
	decide(cur, map[string][]float32{"S001": near(0, 0), "S002": near(0, 0)}, nil)

	got, err := repo.ListSemanticPrecedents(ctx, user, cur, []string{"S002"}) // у S002 уже есть подсказки по словам
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].ChangeID != "S001" || got[0].PastChangeID != "E001" || got[0].ReviewID != past ||
		!got[0].Semantic || got[0].Same || got[0].Choice != "counter" || got[0].Text != "в течение 20 дней" {
		t.Fatalf("only the close decision of the same topic, obligor and role: %+v", got)
	}
	if _, err := repo.ListSemanticPrecedents(ctx, user+100000, cur, nil); !errors.Is(err, core_errors.ErrNotFound) {
		t.Fatalf("other user's review: err = %v", err)
	}
}
