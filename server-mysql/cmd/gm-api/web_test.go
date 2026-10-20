package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testGMWeb(t *testing.T, api http.Handler) *gmWebHandler {
	t.Helper()
	dir := t.TempDir()
	if err := os.Mkdir(filepath.Join(dir, "assets"), 0700); err != nil {
		t.Fatal(err)
	}
	for name, body := range map[string]string{
		"index.html":             "<!doctype html><main>GM application</main>",
		"assets/app-Abc12345.js": "console.log('GM');", ".env": "private",
	} {
		if err := os.WriteFile(filepath.Join(dir, filepath.FromSlash(name)), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
	}
	handler, err := newGMWebHandler(api, dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { handler.Close() })
	return handler
}

func TestGMWebSPARoutesAssetsAndMissingFiles(t *testing.T) {
	h := testGMWeb(t, http.NotFoundHandler())
	for _, route := range []string{"/", "/index.html", "/players/123", "/configs", "/login"} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", route, nil))
		if w.Code != 200 || !strings.Contains(w.Body.String(), "GM application") || w.Header().Get("Cache-Control") != "no-cache" {
			t.Fatalf("SPA %s status=%d body=%q headers=%v", route, w.Code, w.Body.String(), w.Header())
		}
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/assets/app-Abc12345.js", nil))
	if w.Code != 200 || w.Body.String() != "console.log('GM');" || !strings.Contains(w.Header().Get("Content-Type"), "javascript") || !strings.Contains(w.Header().Get("Cache-Control"), "immutable") {
		t.Fatalf("asset response=%d %q %v", w.Code, w.Body.String(), w.Header())
	}
	for _, route := range []string{"/assets/missing.js", "/assets/missing", "/assets", "/favicon-missing.svg", "/.env", "/assets/../.env", "/../private", "/assets//app-Abc12345.js"} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", route, nil))
		if w.Code != 404 || strings.Contains(w.Body.String(), "GM application") || strings.Contains(w.Body.String(), "private") {
			t.Fatalf("invalid file %s status=%d body=%q", route, w.Code, w.Body.String())
		}
	}
	request := httptest.NewRequest("GET", "/assets/app-Abc12345.js", nil)
	request.Header.Set("Range", "bytes=0-6")
	w = httptest.NewRecorder()
	h.ServeHTTP(w, request)
	if w.Code != 206 || w.Body.String() != "console" {
		t.Fatalf("asset range status=%d body=%q", w.Code, w.Body.String())
	}
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("HEAD", "/players/123", nil))
	if w.Code != 200 || w.Body.Len() != 0 {
		t.Fatalf("HEAD route status=%d body=%q", w.Code, w.Body.String())
	}
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/players/123", nil))
	if w.Code != 405 {
		t.Fatalf("POST SPA status=%d", w.Code)
	}
}

func TestGMWebKeepsAPIOriginCookiesAndBodiesAndDiscardsUntrustedProxy(t *testing.T) {
	called := false
	h := testGMWeb(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		body, err := io.ReadAll(r.Body)
		if err != nil || string(body) != `{"action":"verify"}` || r.Method != "POST" || r.Host != "192.168.1.22:8897" || r.URL.RawQuery != "limit=20" || r.Header.Get("X-CSRF-Token") != "test-csrf" || r.Header.Get("Cookie") != "mhq_gm_session=test-session" {
			t.Fatalf("API request was changed: method=%s host=%s query=%s body=%q err=%v", r.Method, r.Host, r.URL.RawQuery, body, err)
		}
		for _, name := range []string{"Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP"} {
			if r.Header.Get(name) != "" {
				t.Fatalf("untrusted proxy header survived: %s", name)
			}
		}
		if !sameOrigin(r, &urlValue{scheme: "http", host: "192.168.1.22:8897"}) || sameOrigin(r, &urlValue{scheme: "http", host: "other-host"}) {
			t.Fatal("public port was lost or spoofed in the CSRF origin check")
		}
		w.Header().Set("Set-Cookie", "mhq_gm_session=next-session; Path=/; HttpOnly")
		w.WriteHeader(202)
		w.Write([]byte(`{"data":"accepted"}`))
	}))
	r := httptest.NewRequest("POST", "http://192.168.1.22:8897/api/v1/players/1/mail?limit=20", strings.NewReader(`{"action":"verify"}`))
	r.Header.Set("Cookie", "mhq_gm_session=test-session")
	r.Header.Set("X-CSRF-Token", "test-csrf")
	for _, name := range []string{"Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP"} {
		r.Header.Set(name, "other-host")
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if !called || w.Code != 202 || !strings.Contains(w.Header().Get("Set-Cookie"), "next-session") || !strings.Contains(w.Body.String(), "accepted") {
		t.Fatalf("API response lost: status=%d body=%q headers=%v", w.Code, w.Body.String(), w.Header())
	}
	if r.Header.Get("X-Forwarded-Host") != "other-host" {
		t.Fatal("handler mutated the caller's request headers")
	}
}

func TestGMWebDoesNotTurnAPIAuthFailuresIntoSPA(t *testing.T) {
	app := newApp(nil, nil, "127.0.0.1:7756", true)
	h := testGMWeb(t, app)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/players", nil))
	if w.Code != 401 || strings.Contains(w.Body.String(), "GM application") || !strings.Contains(w.Header().Get("Content-Type"), "json") {
		t.Fatalf("unauthenticated API status=%d body=%q", w.Code, w.Body.String())
	}
	w = httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/api/v1/auth/login", nil)
	r.ContentLength = 2<<20 + 1
	h.ServeHTTP(w, r)
	if w.Code != 413 {
		t.Fatalf("request larger than the old nginx limit status=%d", w.Code)
	}
}

func TestGMWebRejectsMissingBuildAndEscapingSymlinks(t *testing.T) {
	if h, err := newGMWebHandler(http.NotFoundHandler(), t.TempDir()); err == nil {
		h.Close()
		t.Fatal("missing production index was accepted")
	}
	h := testGMWeb(t, http.NotFoundHandler())
	outside := filepath.Join(t.TempDir(), "private.txt")
	if err := os.WriteFile(outside, []byte("outside-secret"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(h.root.Name(), "escape.txt")); err != nil {
		t.Skip("OS does not permit this symlink test: ", err)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/escape.txt", nil))
	if w.Code != 404 || strings.Contains(w.Body.String(), "outside-secret") {
		t.Fatalf("asset escaped root: status=%d body=%q", w.Code, w.Body.String())
	}
}
