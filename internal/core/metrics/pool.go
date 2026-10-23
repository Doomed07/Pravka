package core_metrics

import (
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
)

// RegisterPool добавляет метрики пула соединений. GaugeFunc не хранит значение,
// а вызывает функцию в момент, когда Prometheus запрашивает /metrics.
func RegisterPool(pool *pgxpool.Pool) {
	gauge := func(name, help string, value func(*pgxpool.Stat) int32) prometheus.Collector {
		return prometheus.NewGaugeFunc(
			prometheus.GaugeOpts{Name: name, Help: help},
			func() float64 { return float64(value(pool.Stat())) },
		)
	}

	Registry.MustRegister(
		gauge("pravki_db_pool_acquired_conns", "Соединения, занятые запросами.", (*pgxpool.Stat).AcquiredConns),
		gauge("pravki_db_pool_idle_conns", "Свободные соединения.", (*pgxpool.Stat).IdleConns),
		gauge("pravki_db_pool_total_conns", "Все открытые соединения.", (*pgxpool.Stat).TotalConns),
	)
}
