package reviews_service

import (
	"context"
	"errors"
	"fmt"
	"time"

	core_domain "github.com/Doomed07/Pravka/internal/core/domain"
	core_errors "github.com/Doomed07/Pravka/internal/core/errors"
	core_logger "github.com/Doomed07/Pravka/internal/core/logger"
	core_metrics "github.com/Doomed07/Pravka/internal/core/metrics"
	"github.com/Doomed07/Pravka/internal/engine"
	"github.com/Doomed07/Pravka/internal/features/reviews/filestore"
	"go.uber.org/zap"
)

// Create отправляет договор движку и сохраняет результат. В базе остаются отчёты; файл контрагента, если задан корень
// хранилища, ещё и кладётся в папку раунда: Контрагент / Договор / Раунд N.
func (s *ReviewsService) Create(ctx context.Context, userID int, req core_domain.ReviewRequest) (core_domain.ContractReview, error) {
	req.Theirs.Name = core_domain.CleanFileName(req.Theirs.Name)
	if req.Base != nil {
		req.Base.Name = core_domain.CleanFileName(req.Base.Name)
	}
	if err := req.Validate(); err != nil {
		core_metrics.ReviewsFailed.WithLabelValues("invalid").Inc()
		return core_domain.ContractReview{}, err
	}
	// очередной раунд существующего договора или новый договор: название и права проверяем до долгого разбора
	var project *core_domain.ProjectSummary
	projectName, cpName, cpINN := "", "", ""
	if req.ProjectID > 0 {
		p, err := s.repo.GetProject(ctx, userID, req.ProjectID)
		if err != nil {
			core_metrics.ReviewsFailed.WithLabelValues("invalid").Inc()
			return core_domain.ContractReview{}, err
		}
		project = &p
	} else {
		var err error
		if projectName, err = core_domain.ProjectName(req.ProjectName, req.Theirs.Name); err != nil {
			core_metrics.ReviewsFailed.WithLabelValues("invalid").Inc()
			return core_domain.ContractReview{}, err
		}
		if cpName, err = core_domain.CounterpartyName(req.CounterpartyName); err != nil {
			core_metrics.ReviewsFailed.WithLabelValues("invalid").Inc()
			return core_domain.ContractReview{}, err
		}
		if cpINN, err = core_domain.CounterpartyINN(req.CounterpartyINN); err != nil {
			core_metrics.ReviewsFailed.WithLabelValues("invalid").Inc()
			return core_domain.ContractReview{}, err
		}
		if req.CounterpartyID > 0 { // чужой или несуществующий контрагент — до долгого разбора
			if _, err := s.repo.GetCounterparty(ctx, userID, req.CounterpartyID); err != nil {
				core_metrics.ReviewsFailed.WithLabelValues("invalid").Inc()
				return core_domain.ContractReview{}, err
			}
		}
	}
	start := time.Now()
	res, xlsx, err := s.engine.Review(ctx, req)
	core_metrics.ReviewDuration.Observe(time.Since(start).Seconds())
	if err != nil {
		reason := "engine"
		var re *engine.RoleError
		switch {
		case errors.As(err, &re):
			reason = "role"
		case errors.Is(err, core_errors.ErrInvalidArgument):
			reason = "bad_file"
		}
		core_metrics.ReviewsFailed.WithLabelValues(reason).Inc()
		return core_domain.ContractReview{}, err
	}
	// роль по плейбуку должна совпадать с ролью прошлых раундов: договор один, и мы в нём одна сторона
	if project != nil && project.OurRole != "" && res.OurRole != "" && project.OurRole != res.OurRole {
		core_metrics.ReviewsFailed.WithLabelValues("invalid").Inc()
		return core_domain.ContractReview{}, fmt.Errorf("в договоре «%s» прошлые раунды разобраны за роль «%s», а выбранный плейбук — за «%s»: %w",
			project.Name, project.OurRole, res.OurRole, core_errors.ErrInvalidArgument)
	}
	// новый договор: находим или создаём контрагента и решаем, в какой папке лежат файлы договора
	round, dir := 1, ""
	if project != nil {
		round, dir = project.Rounds+1, project.Dir
	}
	var counterpartyID int
	if project == nil {
		cp, err := s.repo.EnsureCounterparty(ctx, userID, req.CounterpartyID, cpName, cpINN)
		if err != nil {
			return core_domain.ContractReview{}, fmt.Errorf("ensure counterparty: %w", err)
		}
		counterpartyID = cp.ID
		if dir, err = s.newProjectDir(ctx, userID, cp, projectName); err != nil {
			return core_domain.ContractReview{}, err
		}
	}
	rev := core_domain.ContractReview{
		CounterpartyID: counterpartyID, ProjectDir: dir,
		ProjectID: req.ProjectID, ProjectName: projectName,
		UserID: userID, TheirsName: req.Theirs.Name, Playbook: req.Playbook, PlaybookName: res.PlaybookName,
		OurRole: res.OurRole, ContractType: res.ContractType, Side: res.Side, Counts: res.Counts, Warnings: res.Warnings,
	}
	if req.Base != nil {
		rev.BaseName = req.Base.Name
	}
	// сбой диска разбор не ломает: он остаётся в базе, а юрист видит предупреждение
	if err := s.files.Save(dir, round, filestore.TheirsFile+filestore.Ext(req.Theirs.Name), req.Theirs.Data); err != nil {
		core_logger.FromCtx(ctx).Warn("review: file not saved to disk", zap.Error(err))
		rev.Warnings = append(rev.Warnings, "Файл контрагента не сохранён в папку на диске: "+err.Error()+". Разбор в базе сохранён.")
	}
	out, err := s.repo.CreateReview(ctx, rev, core_domain.ReviewFiles{
		ReportHTML: []byte(res.ReportHTML), ReportXLSX: xlsx, Changes: res.Changes,
		Document: res.Document, Unified: res.Unified,
	})
	if err != nil {
		return core_domain.ContractReview{}, fmt.Errorf("save review: %w", err)
	}
	core_metrics.ReviewsCreated.Inc()
	select {
	case s.nudge <- struct{}{}:
	default:
	}
	return out, nil
}

// newProjectDir — путь папки нового договора «Контрагент/Договор» внутри корня хранилища; при совпадении с другим
// договором (без учёта регистра) добавляется « 2», « 3»… Хранилище выключено — пусто.
func (s *ReviewsService) newProjectDir(ctx context.Context, userID int, cp core_domain.Counterparty, project string) (string, error) {
	if !s.files.Enabled() {
		return "", nil
	}
	cdir := cp.Dir
	if cdir == "" {
		var err error
		if cdir, err = s.repo.AssignCounterpartyDir(ctx, userID, cp.ID, filestore.SafeName(cp.Name)); err != nil {
			return "", fmt.Errorf("assign counterparty dir: %w", err)
		}
	}
	base := cdir + "/" + filestore.SafeName(project)
	dir := base
	for n := 2; ; n++ {
		taken, err := s.repo.ProjectDirTaken(ctx, dir)
		if err != nil {
			return "", err
		}
		if !taken {
			return dir, nil
		}
		dir = fmt.Sprintf("%s %d", base, n)
	}
}
