package core_http_server

import (
	"io/fs"
	"net/http"
	"strings"

	core_http_middleware "github.com/Doomed07/Pravka/internal/core/transport/http/middleware"
)

// RegisterStatic раздаёт файлы из fsys по prefix, например "/static/".
func (s *HTTPServer) RegisterStatic(prefix string, fsys fs.FS) {
	fileServer := http.FileServerFS(noDirFS{fsys})

	s.mux.Handle(
		http.MethodGet+" "+prefix,
		core_http_middleware.RouteLabel(prefix)(
			http.StripPrefix(strings.TrimSuffix(prefix, "/"), fileServer),
		),
	)
}

// noDirFS прячет каталоги: без него FileServer показал бы список файлов
// по адресам вроде /static/ и /static/css/.
type noDirFS struct {
	fs.FS
}

func (f noDirFS) Open(name string) (fs.File, error) {
	file, err := f.FS.Open(name)
	if err != nil {
		return nil, err
	}

	info, err := file.Stat()
	if err != nil {
		_ = file.Close()
		return nil, err
	}

	if info.IsDir() {
		_ = file.Close()
		return nil, fs.ErrNotExist
	}

	return file, nil
}
