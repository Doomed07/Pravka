# Веб-сервис «Правки» в Docker. Первый запуск: make env-init && make up
-include .env
export

DB_URL = postgres://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@pravki-postgres:5432/$(POSTGRES_DB)?sslmode=disable
MODEL ?= $(or $(PRAVKI_LLM_MODEL),hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:Q4_K_M)

.PHONY: env-init up down restart logs migrate migrate-down ps ai-up ai-pull test test-go test-py

# .env со случайными паролями (если .env уже есть — не трогаем)
env-init:
	@if [ -f .env ]; then echo ".env уже есть — оставляю как есть"; exit 0; fi; \
	cp .env.example .env; \
	for key in POSTGRES_PASSWORD ENGINE_TOKEN GRAFANA_ADMIN_PASSWORD; do \
		val=$$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32); \
		sed -i.bak "s|^$$key=.*|$$key=$$val|" .env; \
	done; rm -f .env.bak; mkdir -p playbooks/private; echo "Создан .env"

# Собрать и запустить всё: база, миграции, движок, веб-сервис
up:
	@mkdir -p playbooks/private out
	@docker compose up -d --build pravki-postgres engine
	@echo "Жду базу…"; for i in $$(seq 1 30); do \
		docker compose exec -T pravki-postgres pg_isready -U $(POSTGRES_USER) >/dev/null 2>&1 && break; sleep 2; done
	@$(MAKE) --no-print-directory migrate
	@docker compose up -d --build pravkiapp
	@echo "Готово: http://127.0.0.1:8080"

down:
	@docker compose --profile ai --profile monitoring down

restart: down up

ps:
	@docker compose ps

logs:
	@docker compose logs -f --tail=100 pravkiapp engine

migrate:
	@docker compose run --rm pravki-migrate -path /migrations -database "$(DB_URL)" up

migrate-down:
	@read -p "Откатить последнюю миграцию? [y/N]: " ans; [ "$$ans" = "y" ] && \
		docker compose run --rm pravki-migrate -path /migrations -database "$(DB_URL)" down 1 || echo "Отменено"

# Локальная модель GigaChat 3.1 Lightning через Ollama в Docker. На Mac без видеокарты в Docker она работает медленно —
# быстрее поставить Ollama прямо на Mac и указать PRAVKI_LLM_URL=http://host.docker.internal:11434/v1
ai-up:
	@docker compose --profile ai up -d ollama
	@echo "Теперь: make ai-pull и в .env PRAVKI_LLM_URL=http://ollama:11434/v1, затем make up"

ai-pull:
	@docker compose --profile ai exec ollama ollama pull $(MODEL)

# Тесты без Docker: Go и Python
test: test-go test-py

test-go:
	@go test ./...

test-py:
	@python3 -m pytest -q
