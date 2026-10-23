package core_metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

const (
	LoginSuccess = "success"
	LoginInvalid = "invalid"
)

var (
	Registrations = promauto.With(Registry).NewCounter(prometheus.CounterOpts{
		Name: "pravki_registrations_total",
		Help: "Успешные регистрации.",
	})

	Logins = promauto.With(Registry).NewCounterVec(prometheus.CounterOpts{
		Name: "pravki_logins_total",
		Help: "Попытки входа по результату.",
	}, []string{"result"})

	ReviewsCreated = promauto.With(Registry).NewCounter(prometheus.CounterOpts{
		Name: "pravki_reviews_created_total",
		Help: "Разборы договоров, выполненные успешно.",
	})

	ReviewsFailed = promauto.With(Registry).NewCounterVec(prometheus.CounterOpts{
		Name: "pravki_reviews_failed_total",
		Help: "Разборы, которые не удалось выполнить, по причине.",
	}, []string{"reason"})

	ReviewDuration = promauto.With(Registry).NewHistogram(prometheus.HistogramOpts{
		Name:    "pravki_review_duration_seconds",
		Help:    "Время разбора договора движком.",
		Buckets: []float64{0.5, 1, 2, 5, 10, 30, 60, 120, 300},
	})
)
