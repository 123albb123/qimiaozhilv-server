package main

import (
	"bytes"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"os"
	"path"
	"strings"
	"time"
)

// gmWebHandler serves the production SPA and the existing API on one origin.
// os.Root confines file access even if a deployed asset is a symlink.
type gmWebHandler struct {
	api       http.Handler
	root      *os.Root
	index     []byte
	indexTime time.Time
}

func newGMWebHandler(api http.Handler, directory string) (*gmWebHandler, error) {
	root, err := os.OpenRoot(directory)
	if err != nil {
		return nil, fmt.Errorf("open GM web root: %w", err)
	}
	index, err := root.Open("index.html")
	if err != nil {
		root.Close()
		return nil, fmt.Errorf("open GM index: %w", err)
	}
	defer index.Close()
	info, err := index.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > 2<<20 {
		root.Close()
		return nil, fmt.Errorf("GM index must be a readable regular file of at most 2 MiB")
	}
	body, err := io.ReadAll(index)
	if err != nil {
		root.Close()
		return nil, fmt.Errorf("read GM index: %w", err)
	}
	return &gmWebHandler{api: api, root: root, index: body, indexTime: info.ModTime()}, nil
}

func (h *gmWebHandler) Close() error { return h.root.Close() }

func (h *gmWebHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("X-Frame-Options", "DENY")
	w.Header().Set("Referrer-Policy", "same-origin")
	w.Header().Set("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
	if r.URL.Path == "/api" || strings.HasPrefix(r.URL.Path, "/api/") {
		// This listener is public in compact deployments. Previously nginx
		// replaced these headers; never trust a direct client's claimed proxy.
		request := r.Clone(r.Context())
		for _, name := range []string{"Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP"} {
			request.Header.Del(name)
		}
		if r.ContentLength > 2<<20 {
			http.Error(w, "request body too large", http.StatusRequestEntityTooLarge)
			return
		}
		request.Body = http.MaxBytesReader(w, request.Body, 2<<20)
		h.api.ServeHTTP(w, request)
		return
	}
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	name := strings.TrimPrefix(r.URL.Path, "/")
	if name == "" {
		name = "index.html"
	}
	if !fs.ValidPath(name) || strings.Contains(name, "\\") {
		http.NotFound(w, r)
		return
	}
	for _, segment := range strings.Split(name, "/") {
		if strings.HasPrefix(segment, ".") {
			http.NotFound(w, r)
			return
		}
	}
	if name == "index.html" {
		h.serveIndex(w, r)
		return
	}
	file, err := h.root.Open(name)
	if err != nil {
		// Deep-link refreshes use the SPA, while a missing JS/CSS/image must
		// stay a real 404 instead of returning HTML with a successful status.
		if os.IsNotExist(err) && !strings.HasPrefix(name, "assets/") && path.Ext(name) == "" {
			h.serveIndex(w, r)
			return
		}
		http.NotFound(w, r)
		return
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() {
		http.NotFound(w, r)
		return
	}
	if strings.HasPrefix(name, "assets/") {
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
	} else {
		w.Header().Set("Cache-Control", "no-cache")
	}
	http.ServeContent(w, r, name, info.ModTime(), file)
}

func (h *gmWebHandler) serveIndex(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	http.ServeContent(w, r, "index.html", h.indexTime, bytes.NewReader(h.index))
}
