package core_metrics

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Registry — наш собственный реестр метрик. Глобальный prometheus.DefaultRegisterer
// не используем: так видно, что именно мы отдаём, и тесты не зависят от чужих пакетов.
var Registry = prometheus.NewRegistry()

func init() {
	Registry.MustRegister(
		collectors.NewGoCollector(),                                       // горутины, память, GC
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}), // CPU, открытые файлы (на Linux)
	)
}

// Handler отдаёт метрики в текстовом формате Prometheus.
func Handler() http.Handler {
	return promhttp.HandlerFor(Registry, promhttp.HandlerOpts{})
}
