package main

import (
	"database/sql"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"

	json "github.com/goccy/go-json"
	"golang.org/x/crypto/bcrypt"
)

var adminRoleDescriptions = map[string]string{
	"superadmin": "超级管理员：全部权限", "operator": "运营：角色、奖励和配置", "support": "客服：查询、邮件和恢复",
	"config-editor": "配置编辑：校验、发布及回滚", "auditor": "审计：全量只读", "readonly": "只读：账号和角色查询",
	"subgm": "子 GM：仅绑定的游戏账号",
}

type adminChange struct {
	Username    string   `json:"username"`
	DisplayName string   `json:"displayName"`
	Password    string   `json:"password"`
	Roles       []string `json:"roles"`
	Active      bool     `json:"active"`
	Reason      string   `json:"reason"`
}

func validateAdminChange(req adminChange, create bool) error {
	if create && !subGMUsernamePattern.MatchString(strings.TrimSpace(req.Username)) {
		return fmt.Errorf("登录名须为 3-64 位字母、数字、下划线、点或连字符")
	}
	if (create || req.Password != "") && (len(req.Password) < 12 || len(req.Password) > 72) {
		return fmt.Errorf("密码长度须为 12-72 字节")
	}
	if len(req.DisplayName) > 191 {
		return fmt.Errorf("显示名称过长")
	}
	if len(req.Roles) == 0 {
		return fmt.Errorf("至少选择一个角色")
	}
	seen := map[string]bool{}
	for _, role := range req.Roles {
		if adminRoleDescriptions[role] == "" || seen[role] {
			return fmt.Errorf("角色无效或重复")
		}
		seen[role] = true
	}
	if seen["subgm"] && len(req.Roles) != 1 {
		return fmt.Errorf("子 GM 不可与其他角色混用")
	}
	if strings.TrimSpace(req.Reason) == "" || len(req.Reason) > 500 {
		return fmt.Errorf("请填写不超过 500 字节的操作原因")
	}
	return nil
}

func adminAudit(tx *sql.Tx, r *http.Request, rid string, session *sessionData, action string, target int64, before, after any, reason string) error {
	b, _ := json.Marshal(before)
	a, _ := json.Marshal(after)
	_, err := tx.ExecContext(r.Context(), `INSERT INTO gm_audit_logs
		(request_id, admin_id, action, target_type, target_id, before_json, after_json, reason, client_ip, user_agent, result, created_at)
		VALUES (?, ?, ?, 'admin', ?, ?, ?, ?, ?, ?, 'completed', ?)`, rid, session.AdminID, action, strconvI64(target), string(b), string(a), reason, clientIP(r), truncate(r.UserAgent(), 500), time.Now().Unix())
	return err
}

func (a *App) handleAdmins(w http.ResponseWriter, r *http.Request, rid string, session *sessionData, path string) {
	if !hasPermission(session, "admins.manage") {
		writeError(w, 403, rid, "forbidden", "仅超级管理员可管理管理员")
		return
	}
	if path == "/api/v1/admins/roles" && r.Method == http.MethodGet {
		roles := make([]map[string]string, 0, len(adminRoleDescriptions))
		names := make([]string, 0, len(adminRoleDescriptions))
		for name := range adminRoleDescriptions {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			roles = append(roles, map[string]string{"name": name, "description": adminRoleDescriptions[name]})
		}
		writeJSON(w, 200, rid, map[string]any{"items": roles}, nil)
		return
	}
	if path == "/api/v1/admins" && r.Method == http.MethodGet {
		a.listAdmins(w, r, rid)
		return
	}
	if r.Method != http.MethodPost {
		writeError(w, 405, rid, "method_not_allowed", "请求方法不支持")
		return
	}
	if !a.checkCSRF(r, session) {
		writeError(w, 403, rid, "csrf_failed", "请求校验失败")
		return
	}
	create := path == "/api/v1/admins"
	id := int64(0)
	if !create {
		id = parseInt64Param(strings.TrimPrefix(path, "/api/v1/admins/"), 0)
		if id <= 0 {
			writeError(w, 404, rid, "not_found", "管理员不存在")
			return
		}
		if id == session.AdminID {
			writeError(w, 409, rid, "self_edit_forbidden", "请使用修改密码入口；自己的角色与启用状态须由其他超级管理员调整")
			return
		}
	}
	var req adminChange
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 32<<10)).Decode(&req); err != nil {
		writeError(w, 400, rid, "invalid_json", "请求格式错误")
		return
	}
	if err := validateAdminChange(req, create); err != nil {
		writeError(w, 422, rid, "invalid_admin", err.Error())
		return
	}
	hash := ""
	if req.Password != "" {
		raw, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
		if err != nil {
			writeError(w, 500, rid, "hash_failed", "密码处理失败")
			return
		}
		hash = string(raw)
	}
	tx, err := a.db.BeginTx(r.Context(), nil)
	if err != nil {
		writeError(w, 500, rid, "database_error", "管理员保存失败")
		return
	}
	defer tx.Rollback()
	// Serialize administrator changes so no concurrent role update can remove
	// the last active superadministrator through two different target rows.
	locked, err := tx.QueryContext(r.Context(), `SELECT id FROM gm_admin_users ORDER BY id FOR UPDATE`)
	if err != nil {
		writeError(w, 500, rid, "database_error", "管理员保存失败")
		return
	}
	for locked.Next() {
		var value int64
		if err = locked.Scan(&value); err != nil {
			break
		}
	}
	rowsErr := locked.Err()
	locked.Close()
	if err != nil || rowsErr != nil {
		writeError(w, 500, rid, "database_error", "管理员保存失败")
		return
	}
	// Re-check the actor inside the lock; a concurrent change may have revoked
	// the session after request authentication but before this transaction.
	var actor int
	if err = tx.QueryRowContext(r.Context(), `SELECT COUNT(*) FROM gm_admin_users u JOIN gm_admin_roles ar ON ar.admin_id=u.id JOIN gm_roles r ON r.id=ar.role_id WHERE u.id=? AND u.status=1 AND u.updated_at=? AND r.name='superadmin'`, session.AdminID, session.AuthVersion).Scan(&actor); err != nil || actor != 1 {
		writeError(w, 403, rid, "forbidden", "超级管理员权限已变更，请重新登录")
		return
	}
	var before any
	version := time.Now().UnixNano()
	status := 0
	if req.Active {
		status = 1
	}
	if create {
		result, insertErr := tx.ExecContext(r.Context(), `INSERT INTO gm_admin_users (username, password_hash, display_name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)`, strings.TrimSpace(req.Username), hash, strings.TrimSpace(req.DisplayName), status, time.Now().Unix(), version)
		if insertErr != nil {
			writeError(w, 409, rid, "admin_conflict", "管理员登录名已存在或无法创建")
			return
		}
		id, err = result.LastInsertId()
	} else {
		var username, display string
		var previousStatus int
		if err = tx.QueryRowContext(r.Context(), `SELECT username, display_name, status FROM gm_admin_users WHERE id=?`, id).Scan(&username, &display, &previousStatus); err != nil {
			writeError(w, 404, rid, "not_found", "管理员不存在")
			return
		}
		before = map[string]any{"username": username, "displayName": display, "active": previousStatus == 1}
		_, err = tx.ExecContext(r.Context(), `UPDATE gm_admin_users SET display_name=?, status=?, updated_at=?, password_hash=IF(?='',password_hash,?) WHERE id=?`, strings.TrimSpace(req.DisplayName), status, version, hash, hash, id)
	}
	if err == nil {
		_, err = tx.ExecContext(r.Context(), `DELETE FROM gm_admin_roles WHERE admin_id=?`, id)
	}
	for _, role := range req.Roles {
		if err != nil {
			break
		}
		_, err = tx.ExecContext(r.Context(), `INSERT INTO gm_roles (name, description) VALUES (?, ?) ON DUPLICATE KEY UPDATE description=VALUES(description)`, role, adminRoleDescriptions[role])
		if err == nil {
			_, err = tx.ExecContext(r.Context(), `INSERT INTO gm_admin_roles (admin_id, role_id) SELECT ?, id FROM gm_roles WHERE name=?`, id, role)
		}
	}
	if err == nil {
		err = adminAudit(tx, r, rid, session, "admin.save", id, before, map[string]any{"displayName": req.DisplayName, "active": req.Active, "roles": req.Roles, "passwordChanged": hash != ""}, req.Reason)
	}
	if err == nil {
		err = tx.Commit()
	}
	if err != nil {
		writeError(w, 500, rid, "database_error", "管理员保存失败，已回滚")
		return
	}
	writeJSON(w, 200, rid, map[string]any{"id": strconvI64(id), "saved": true}, nil)
}

func (a *App) listAdmins(w http.ResponseWriter, r *http.Request, rid string) {
	rows, err := a.db.QueryContext(r.Context(), `SELECT u.id,u.username,u.display_name,u.status,u.last_login_at,GROUP_CONCAT(r.name ORDER BY r.name SEPARATOR ',') FROM gm_admin_users u LEFT JOIN gm_admin_roles ar ON ar.admin_id=u.id LEFT JOIN gm_roles r ON r.id=ar.role_id GROUP BY u.id ORDER BY u.id LIMIT 200`)
	if err != nil {
		writeError(w, 500, rid, "query_failed", "管理员查询失败")
		return
	}
	defer rows.Close()
	items := make([]map[string]any, 0)
	for rows.Next() {
		var id int64
		var name, display string
		var status int
		var last sql.NullInt64
		var roles sql.NullString
		if err := rows.Scan(&id, &name, &display, &status, &last, &roles); err != nil {
			writeError(w, 500, rid, "query_failed", "管理员查询失败")
			return
		}
		roleList := []string{}
		if roles.Valid && roles.String != "" {
			roleList = strings.Split(roles.String, ",")
		}
		items = append(items, map[string]any{"id": strconvI64(id), "username": name, "displayName": display, "active": status == 1, "lastLogin": strconvI64(last.Int64), "roles": roleList})
	}
	if rows.Err() != nil {
		writeError(w, 500, rid, "query_failed", "管理员查询失败")
		return
	}
	writeJSON(w, 200, rid, map[string]any{"items": items}, nil)
}

func (a *App) handleOwnPassword(w http.ResponseWriter, r *http.Request, rid string, session *sessionData) {
	if r.Method != http.MethodPost {
		writeError(w, 405, rid, "method_not_allowed", "请求方法不支持")
		return
	}
	if !a.checkCSRF(r, session) {
		writeError(w, 403, rid, "csrf_failed", "请求校验失败")
		return
	}
	var req struct {
		Current  string `json:"currentPassword"`
		Password string `json:"newPassword"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&req); err != nil || len(req.Password) < 12 || len(req.Password) > 72 {
		writeError(w, 422, rid, "invalid_password", "新密码须为 12-72 字节")
		return
	}
	tx, err := a.db.BeginTx(r.Context(), nil)
	if err != nil {
		writeError(w, 500, rid, "database_error", "密码修改失败")
		return
	}
	defer tx.Rollback()
	var old string
	if err := tx.QueryRowContext(r.Context(), `SELECT password_hash FROM gm_admin_users WHERE id=? AND status=1 AND updated_at=? FOR UPDATE`, session.AdminID, session.AuthVersion).Scan(&old); err != nil || bcrypt.CompareHashAndPassword([]byte(old), []byte(req.Current)) != nil {
		writeError(w, 403, rid, "invalid_credentials", "当前密码错误")
		return
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err == nil {
		_, err = tx.ExecContext(r.Context(), `UPDATE gm_admin_users SET password_hash=?, updated_at=? WHERE id=?`, string(hash), time.Now().UnixNano(), session.AdminID)
	}
	if err == nil {
		err = adminAudit(tx, r, rid, session, "auth.password", session.AdminID, nil, map[string]bool{"passwordChanged": true}, "本人修改密码")
	}
	if err == nil {
		err = tx.Commit()
	}
	if err != nil {
		writeError(w, 500, rid, "database_error", "密码修改失败，已回滚")
		return
	}
	_ = a.sessions.Delete(r.Context(), session.ID)
	a.clearSessionCookies(w)
	writeJSON(w, 200, rid, map[string]bool{"changed": true, "loginRequired": true}, nil)
}
