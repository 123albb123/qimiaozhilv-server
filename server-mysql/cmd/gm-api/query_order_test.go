package main

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// Reuse the isolated admin-lifecycle database so this verifies real SQL,
// pagination boundaries and the authenticated routes without another schema.
func checkQueryOrdering(t *testing.T, db *sql.DB, app *App, cookies []*http.Cookie) {
	t.Helper()
	if _, err := db.Exec(`INSERT INTO accounts (id,account,password,create_time) VALUES
		(10001,'orderingAlpha','NeverReturnThisPassword',1),(10002,'orderingBeta','NeverReturnThisPassword',2)`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO players (id,account_id,name) VALUES
		(100001,10001,'排序甲'),(100002,10002,'排序乙')`); err != nil {
		t.Fatal(err)
	}
	for _, spec := range []struct{ path, id, next string }{
		{"/api/v1/accounts?query=ordering&order=desc&limit=1", "10002", "10002"},
		{"/api/v1/accounts?query=ordering&order=desc&limit=1&cursor=10002", "10001", ""},
		{"/api/v1/accounts?query=ordering&order=asc&limit=1&cursor=10001", "10002", ""},
		{"/api/v1/players?query=ordering&order=desc&limit=1", "100002", "100002"},
		{"/api/v1/players?query=ordering&order=desc&limit=1&cursor=100002", "100001", ""},
		{"/api/v1/players?query=ordering&order=asc&limit=1&cursor=100001", "100002", ""},
	} {
		req := httptest.NewRequest("GET", spec.path, nil)
		for _, cookie := range cookies {
			req.AddCookie(cookie)
		}
		res := httptest.NewRecorder()
		app.ServeHTTP(res, req)
		var body struct {
			Data struct {
				Items []struct {
					ID string `json:"id"`
				}
				Next string `json:"nextCursor"`
			} `json:"data"`
		}
		if res.Code != 200 || json.Unmarshal(res.Body.Bytes(), &body) != nil ||
			len(body.Data.Items) != 1 || body.Data.Items[0].ID != spec.id || body.Data.Next != spec.next {
			t.Fatalf("ordered page %s: %d %s", spec.path, res.Code, res.Body.String())
		}
		if strings.Contains(res.Body.String(), "NeverReturnThisPassword") || strings.Contains(res.Body.String(), `"password"`) {
			t.Fatal("account query exposed a password")
		}
	}
}
