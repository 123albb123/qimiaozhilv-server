package main

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/go-sql-driver/mysql"
	"golang.org/x/crypto/bcrypt"
	"mhqserver/internal/mysqlschema"
)

func TestAdminLifecycleMySQL(t *testing.T) {
	dsn := os.Getenv("MHQ_TEST_MYSQL_DSN")
	if dsn == "" {
		t.Skip("requires isolated MySQL with CREATE DATABASE permission")
	}
	cfg, err := mysql.ParseDSN(dsn)
	if err != nil {
		t.Fatal(err)
	}
	cfg.DBName = fmt.Sprintf("mhq_test_admin_%d_%d", os.Getpid(), time.Now().UnixNano())
	db, _, err := mysqlschema.Open(cfg.FormatDSN())
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	t.Cleanup(func() {
		bootstrap := *cfg
		bootstrap.DBName = ""
		cleanup, err := sql.Open("mysql", bootstrap.FormatDSN())
		if err != nil {
			t.Error(err)
			return
		}
		defer cleanup.Close()
		if _, err := cleanup.Exec("DROP DATABASE `" + cfg.DBName + "`"); err != nil {
			t.Error(err)
		}
	})
	hash, _ := bcrypt.GenerateFromPassword([]byte("RootSecret123456"), bcrypt.DefaultCost)
	if _, err := db.Exec(`INSERT INTO gm_admin_users (username,password_hash,status,created_at,updated_at) VALUES ('rootadmin',?,1,1,1)`, string(hash)); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO gm_roles (name) VALUES ('superadmin');`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO gm_admin_roles (admin_id,role_id) SELECT u.id,r.id FROM gm_admin_users u,gm_roles r`); err != nil {
		t.Fatal(err)
	}
	app := newApp(db, nil, "", true)
	call := func(path, method string, payload any, cookies []*http.Cookie, csrf string) *httptest.ResponseRecorder {
		raw, _ := json.Marshal(payload)
		req := httptest.NewRequest(method, path, bytes.NewReader(raw))
		for _, cookie := range cookies {
			req.AddCookie(cookie)
		}
		if csrf != "" {
			req.Header.Set("X-CSRF-Token", csrf)
		}
		res := httptest.NewRecorder()
		app.ServeHTTP(res, req)
		return res
	}
	login := func(username, password string) ([]*http.Cookie, string) {
		res := call("/api/v1/auth/login", "POST", map[string]string{"username": username, "password": password}, nil, "")
		if res.Code != 200 {
			t.Fatalf("login %s: %d %s", username, res.Code, res.Body.String())
		}
		var body struct {
			Data struct {
				CSRF string `json:"csrfToken"`
			}
		}
		if err := json.Unmarshal(res.Body.Bytes(), &body); err != nil {
			t.Fatal(err)
		}
		return res.Result().Cookies(), body.Data.CSRF
	}
	rootCookies, rootCSRF := login("rootadmin", "RootSecret123456")
	checkQueryOrdering(t, db, app, rootCookies)
	rootRequest := adminChange{Username: "second", Password: "SecondSecret123456", Roles: []string{"readonly"}, Active: true, Reason: "isolated lifecycle regression"}
	res := call("/api/v1/admins", "POST", rootRequest, rootCookies, rootCSRF)
	if res.Code != 200 {
		t.Fatalf("create: %d %s", res.Code, res.Body.String())
	}
	var body struct {
		Data struct {
			ID string `json:"id"`
		}
	}
	json.Unmarshal(res.Body.Bytes(), &body)
	secondCookies, secondCSRF := login("second", "SecondSecret123456")
	if res := call("/api/v1/admins", "GET", nil, secondCookies, ""); res.Code != 403 {
		t.Fatalf("readonly admin management = %d", res.Code)
	}
	if res := call("/api/v1/auth/password", "POST", map[string]string{"currentPassword": "wrong", "newPassword": "ChangedSecret123456"}, secondCookies, secondCSRF); res.Code != 403 {
		t.Fatalf("wrong old password = %d", res.Code)
	}
	if res := call("/api/v1/auth/me", "GET", nil, secondCookies, ""); res.Code != 200 {
		t.Fatalf("rejected change invalidated session: %d", res.Code)
	}
	if res := call("/api/v1/auth/password", "POST", map[string]string{"currentPassword": "SecondSecret123456", "newPassword": "ChangedSecret123456"}, secondCookies, secondCSRF); res.Code != 200 {
		t.Fatalf("change password: %d %s", res.Code, res.Body.String())
	}
	if res := call("/api/v1/auth/me", "GET", nil, secondCookies, ""); res.Code != 401 {
		t.Fatalf("old session survived password change = %d", res.Code)
	}
	secondCookies, _ = login("second", "ChangedSecret123456")
	rootRequest.Password = ""
	rootRequest.Active = false
	if res := call("/api/v1/admins/"+body.Data.ID, "POST", rootRequest, rootCookies, rootCSRF); res.Code != 200 {
		t.Fatalf("disable: %d %s", res.Code, res.Body.String())
	}
	if res := call("/api/v1/auth/me", "GET", nil, secondCookies, ""); res.Code != 401 {
		t.Fatalf("disabled session still usable = %d", res.Code)
	}
	if res := call("/api/v1/auth/login", "POST", map[string]string{"username": "second", "password": "ChangedSecret123456"}, nil, ""); res.Code != 401 {
		t.Fatalf("disabled login = %d", res.Code)
	}
	var rootID int64
	db.QueryRow(`SELECT id FROM gm_admin_users WHERE username='rootadmin'`).Scan(&rootID)
	if res := call("/api/v1/admins/"+strconvI64(rootID), "POST", rootRequest, rootCookies, rootCSRF); res.Code != 409 {
		t.Fatalf("last superadmin could edit itself = %d", res.Code)
	}
	// Several commands share one second. Pagination must use both time and
	// request ID to avoid repeating or losing any command at a page boundary.
	for i := 0; i < 6; i++ {
		if _, err := db.Exec(`INSERT INTO gm_command_records (request_id,action,status,created_at,expires_at) VALUES (?,'test.page','completed',100,0)`, fmt.Sprintf("page-%d", i)); err != nil {
			t.Fatal(err)
		}
	}
	seen, cursor := map[string]bool{}, ""
	for page := 0; page < 4; page++ {
		res := call("/api/v1/commands?limit=2&cursor="+url.QueryEscape(cursor)+"&query=test.page", "GET", nil, rootCookies, "")
		if res.Code != 200 {
			t.Fatalf("command page: %d %s", res.Code, res.Body.String())
		}
		var body struct {
			Data struct {
				Items []struct {
					ID string `json:"requestId"`
				} `json:"items"`
				Cursor string `json:"nextCursor"`
			}
		}
		if err := json.Unmarshal(res.Body.Bytes(), &body); err != nil {
			t.Fatal(err)
		}
		for _, item := range body.Data.Items {
			if seen[item.ID] {
				t.Fatalf("repeated command across pages: %s", item.ID)
			}
			seen[item.ID] = true
		}
		cursor = body.Data.Cursor
		if cursor == "" {
			break
		}
	}
	if len(seen) != 6 {
		t.Fatalf("command pagination lost rows: %v", seen)
	}
	// A configuration, its previous snapshot, and its audit must move as one
	// transaction. These synthetic rows exist only in this dedicated test DB.
	initial := []any{[]any{int64(1), map[string]any{"Name": "Original", "Price": int64(10)}}}
	if _, err := replaceGMConfig(context.Background(), db, "ShopBase", initial, "fixture", "test fixture"); err != nil {
		t.Fatal(err)
	}
	res = call("/api/v1/configs/ShopBase/drafts", "POST", map[string]string{"contentYaml": "- [1, {Name: Original, Price: 10}]", "baseRevision": "9007199254740993"}, rootCookies, rootCSRF)
	if res.Code != 201 || !strings.Contains(res.Body.String(), `"baseRevision":"9007199254740993"`) {
		t.Fatalf("browser string revision draft failed: %d %s", res.Code, res.Body.String())
	}
	res = call("/api/v1/configs/ShopBase/publish", "POST", map[string]string{"contentYaml": "[]", "note": "must reject"}, rootCookies, rootCSRF)
	if res.Code != 422 {
		t.Fatalf("empty config accepted: %d %s", res.Code, res.Body.String())
	}
	res = call("/api/v1/configs/ShopBase/publish", "POST", map[string]string{"contentYaml": "- [1, {Name: Updated, Price: 20}]", "note": "valid config test"}, rootCookies, rootCSRF)
	if res.Code != 200 || !strings.Contains(res.Body.String(), `"reloadStatus":"notification_failed"`) {
		t.Fatalf("missing Redis was reported as applied: %d %s", res.Code, res.Body.String())
	}
	var baseline int64
	if err := db.QueryRow(`SELECT MIN(revision) FROM gm_config_snapshots WHERE config_name='ShopBase'`).Scan(&baseline); err != nil || baseline == 0 {
		t.Fatalf("original snapshot missing: %d %v", baseline, err)
	}
	res = call(fmt.Sprintf("/api/v1/configs/ShopBase/revisions/%d/rollback", baseline), "POST", map[string]string{"note": "restore fixture"}, rootCookies, rootCSRF)
	if res.Code != 200 {
		t.Fatalf("rollback: %d %s", res.Code, res.Body.String())
	}
	assertOriginal := func() {
		var count int
		if err := db.QueryRow(`SELECT COUNT(*) FROM game_config_nodes WHERE config_name='ShopBase' AND field_name='Name' AND string_value='Original'`).Scan(&count); err != nil || count != 1 {
			t.Fatalf("original configuration not preserved: %d %v", count, err)
		}
	}
	assertOriginal()
	var beforeRevisions, afterRevisions int
	db.QueryRow(`SELECT COUNT(*) FROM game_config_revisions`).Scan(&beforeRevisions)
	res = call("/api/v1/configs/ShopBase/publish", "POST", map[string]string{"contentYaml": "- [1, {Name: Original, Price: 10}]", "note": "retry same value"}, rootCookies, rootCSRF)
	if res.Code != 200 {
		t.Fatalf("same-value retry: %d %s", res.Code, res.Body.String())
	}
	db.QueryRow(`SELECT COUNT(*) FROM game_config_revisions`).Scan(&afterRevisions)
	if afterRevisions != beforeRevisions {
		t.Fatal("same-value submission created another configuration revision")
	}
	if _, err := db.Exec(`CREATE TRIGGER test_deny_config_snapshot BEFORE INSERT ON gm_config_snapshots FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='injected snapshot failure'`); err != nil {
		t.Fatal(err)
	}
	res = call("/api/v1/configs/ShopBase/publish", "POST", map[string]string{"contentYaml": "- [1, {Name: Rejected, Price: 30}]", "note": "injected snapshot failure"}, rootCookies, rootCSRF)
	if res.Code != 500 {
		t.Fatalf("snapshot failure returned success: %d %s", res.Code, res.Body.String())
	}
	assertOriginal()
	db.QueryRow(`SELECT COUNT(*) FROM game_config_revisions`).Scan(&afterRevisions)
	if afterRevisions != beforeRevisions {
		t.Fatal("failed transaction left a configuration revision")
	}
	if _, err := db.Exec(`DROP TRIGGER test_deny_config_snapshot`); err != nil {
		t.Fatal(err)
	}
	rows, err := db.QueryContext(context.Background(), `SELECT CONCAT(COALESCE(before_json,''),COALESCE(after_json,'')) FROM gm_audit_logs WHERE action IN ('admin.save','auth.password')`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	count := 0
	for rows.Next() {
		var raw string
		if err := rows.Scan(&raw); err != nil {
			t.Fatal(err)
		}
		if strings.Contains(raw, "Secret") || strings.Contains(raw, string(hash)) {
			t.Fatal("credential leaked into audit")
		}
		count++
	}
	if count != 3 {
		t.Fatalf("expected 3 committed management audits, got %d", count)
	}
}

func TestAdminRoleEscalationAndMalformedInputsRejected(t *testing.T) {
	for _, roles := range [][]string{{}, {"unknown"}, {"superadmin", "superadmin"}, {"subgm", "superadmin"}} {
		if err := validateAdminChange(adminChange{Username: "admin", Password: "LongPassword123456", Roles: roles, Reason: "test"}, true); err == nil {
			t.Fatalf("invalid roles accepted: %v", roles)
		}
	}
}
