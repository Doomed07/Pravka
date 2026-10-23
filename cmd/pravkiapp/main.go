package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	core_auth "github.com/Doomed07/Pravka/internal/core/auth"
	core_config "github.com/Doomed07/Pravka/internal/core/config"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
	core_postgres_pgx "github.com/Doomed07/Pravka/internal/core/repository/postgres/pool/pgx"
	core_http_middleware "github.com/Doomed07/Pravka/internal/core/transport/http/middleware"
	core_http_server "github.com/Doomed07/Pravka/internal/core/transport/http/server"
	"github.com/Doomed07/Pravka/internal/engine"
	auth_repository_postgres "github.com/Doomed07/Pravka/internal/features/auth/repository/postgres"
	auth_service "github.com/Doomed07/Pravka/internal/features/auth/service"
	auth_transport_http "github.com/Doomed07/Pravka/internal/features/auth/transport/http"
	law_repository_postgres "github.com/Doomed07/Pravka/internal/features/law/repository/postgres"
	law_service "github.com/Doomed07/Pravka/internal/features/law/service"
	reviews_repository_postgres "github.com/Doomed07/Pravka/internal/features/reviews/repository/postgres"
	reviews_service "github.com/Doomed07/Pravka/internal/features/reviews/service"
	reviews_transport_http "github.com/Doomed07/Pravka/internal/features/reviews/transport/http"
	"github.com/Doomed07/Pravka/web"
	"go.uber.org/zap"
)

// Веб-сервис «Правки»: вход, загрузка договоров, отчёты. Разбор выполняет движок на Python (internal/engine).
func main() {
	cfg := core_config.NewConfigMust()
	time.Local = cfg.TimeZone
	authConfig := core_auth.NewConfigMust()

	ctx, cancel := signal.NotifyContext(
		context.Background(),
		syscall.SIGINT, syscall.SIGTERM,
	)
	defer cancel()

	logger, err := core_logger.NewLogger(core_logger.NewConfigMust())
	if err != nil {
		fmt.Println("Failed to init application logger:", err)
		os.Exit(1)
	}
	defer logger.Close()

	logger.Debug("application time zone", zap.Any("zone", time.Local))

	logger.Debug("initializing connection pool")
	pool, err := core_postgres_pgx.NewConnPool(
		core_postgres_pgx.NewConfigMust(),
		ctx,
	)
	if err != nil {
		logger.Fatal("failed to init postgres connection pool", zap.Error(err))
	}
	defer pool.Close()
	core_metrics.RegisterPool(pool.Pool)

	logger.Debug("initializing feature", zap.String("feature", "Auth"))
	authRepository := auth_repository_postgres.NewAuthRepository(pool)
	authService, err := auth_service.NewAuthService(authRepository, authConfig.BcryptCost, authConfig.SessionTTL)
	if err != nil {
		logger.Fatal("failed to init auth service", zap.Error(err))
	}
	authTransportHTTP := auth_transport_http.NewAuthHTTPHandler(authService, authConfig.SessionTTL, authConfig.CookieSecure, authConfig.SignupCode)

	logger.Debug("initializing feature", zap.String("feature", "Reviews"))
	engineClient := engine.NewClient(engine.NewConfigMust())
	reviewsRepository := reviews_repository_postgres.NewReviewsRepository(pool)
	reviewsService := reviews_service.NewReviewsService(reviewsRepository, engineClient)
	reviewsTransportHTTP := reviews_transport_http.NewReviewsHTTPHandler(reviewsService)

	// нормы ГК РФ для подсказок: загрузка в фоне, сайт работает и без них
	lawService := law_service.NewLawService(law_repository_postgres.NewLawRepository(pool), engineClient)
	go lawService.Run(ctx, logger)

	logger.Debug("initializing HTTP server")
	httpServer := core_http_server.NewHTTPServer(
		core_http_server.NewConfigMust(),
		logger,
		core_http_middleware.Metrics(),
		core_http_middleware.CORS(),
		core_http_middleware.RequestID(),
		core_http_middleware.Logger(logger),
		core_http_middleware.Trace(),
		core_http_middleware.Panic(),
	)

	apiVersionRouterV1 := core_http_server.NewAPIVersionRouter(
		core_http_server.ApiVersion1,
		core_http_middleware.SameOrigin(),
		core_http_middleware.Authenticate(authService),
	)

	apiVersionRouterV1.RegisterRoutes(authTransportHTTP.Routes()...)
	apiVersionRouterV1.RegisterRoutes(reviewsTransportHTTP.Routes()...)

	httpServer.RegisterAPIRouters(apiVersionRouterV1)

	httpServer.RegisterStatic("/static/", web.Static())
	httpServer.RegisterRoutes(web.Routes()...)

	logger.Debug("initializing metrics server")
	metricsServer := core_http_server.NewHTTPServer(
		core_http_server.NewMetricsConfigMust(),
		logger,
	)
	metricsServer.RegisterRoutes(core_http_server.Route{
		Method:  http.MethodGet,
		Path:    "/metrics",
		Handler: core_metrics.Handler().ServeHTTP,
	})

	go func() {
		if err := metricsServer.Run(ctx); err != nil {
			logger.Error("Failed to run metrics server", zap.Error(err))
		}
	}()

	if err := httpServer.Run(ctx); err != nil {
		logger.Error("Failed to run server", zap.Error(err))
	}
}
