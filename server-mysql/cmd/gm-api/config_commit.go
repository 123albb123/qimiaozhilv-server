package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"time"

	json "github.com/goccy/go-json"
	"gopkg.in/yaml.v3"
)

func saveConfigSnapshot(ctx context.Context, tx *sql.Tx, revision int64, name, text, hash, publisher, note string) error {
	_, err := tx.ExecContext(ctx, `INSERT INTO gm_config_snapshots (revision,config_name,content_yaml,content_hash,publisher,note,created_at) VALUES (?,?,?,?,?,?,?)`, revision, name, text, hash, publisher, truncate(note, 255), time.Now().Unix())
	return err
}

// commitConfig uses the existing tree/revision/snapshot tables. Every change,
// its previous effective configuration, and its audit either commit together
// or leave the old configuration untouched.
func (a *App) commitConfig(ctx context.Context, r *http.Request, rid, name string, value any, note string, session *sessionData, action string, draftID int64) (int64, string, error) {
	if err := validateGMConfig(name, value); err != nil {
		return 0, "", err
	}
	encoded, err := yaml.Marshal(value)
	if err != nil {
		return 0, "", err
	}
	hash := fmt.Sprintf("%x", sha256Bytes(encoded))
	tx, err := a.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return 0, "", err
	}
	defer tx.Rollback()
	old, err := readConfigWith(ctx, tx, name)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return 0, "", err
	}
	var previous int64
	var previousHash string
	err = tx.QueryRowContext(ctx, `SELECT revision,content_hash FROM gm_config_snapshots WHERE config_name=? ORDER BY revision DESC LIMIT 1`, name).Scan(&previous, &previousHash)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return 0, "", err
	}
	oldHash := ""
	if old != nil {
		before, err := yaml.Marshal(old)
		if err != nil {
			return 0, "", err
		}
		oldHash = fmt.Sprintf("%x", sha256Bytes(before))
		if oldHash != previousHash {
			result, err := tx.ExecContext(ctx, `INSERT INTO game_config_revisions (published_at,publisher,note) VALUES (?,?,?)`, time.Now().Unix(), session.Username, "[GM:"+name+"] 修改前有效配置快照")
			if err != nil {
				return 0, "", err
			}
			previous, err = result.LastInsertId()
			if err != nil {
				return 0, "", err
			}
			if err := saveConfigSnapshot(ctx, tx, previous, name, string(before), oldHash, session.Username, "修改前有效配置快照"); err != nil {
				return 0, "", err
			}
		}
	}
	revision := previous
	// Repeated submissions of the same effective tree reuse the snapshot.
	if oldHash != hash || revision == 0 {
		revision, err = replaceGMConfigTx(ctx, tx, name, value, session.Username, note)
		if err != nil {
			return 0, "", err
		}
		if err := saveConfigSnapshot(ctx, tx, revision, name, string(encoded), hash, session.Username, note); err != nil {
			return 0, "", err
		}
	}
	if draftID > 0 {
		if _, err := tx.ExecContext(ctx, `UPDATE gm_config_drafts SET status='published',updated_at=? WHERE draft_id=? AND config_name=?`, time.Now().Unix(), draftID, name); err != nil {
			return 0, "", err
		}
	}
	before, _ := json.Marshal(map[string]any{"revision": strconvI64(previous), "contentHash": oldHash})
	after, _ := json.Marshal(map[string]any{"revision": strconvI64(revision), "contentHash": hash})
	_, err = tx.ExecContext(ctx, `INSERT INTO gm_audit_logs (request_id,admin_id,action,target_type,target_id,before_json,after_json,reason,client_ip,user_agent,result,created_at) VALUES (?,?,?,'config',?,?,?,?,?,?,'completed',?)`, rid, session.AdminID, action, name, string(before), string(after), truncate(note, 500), clientIP(r), truncate(r.UserAgent(), 500), time.Now().Unix())
	if err != nil {
		return 0, "", err
	}
	if err := tx.Commit(); err != nil {
		return 0, "", err
	}
	return revision, hash, nil
}

func (a *App) notifyConfigReload(ctx context.Context, revision int64, name string) (string, string) {
	if a.redis == nil {
		return "notification_failed", "Redis 不可用；配置已保存，尚未确认游戏服加载"
	}
	if err := a.redis.Publish(ctx, "mhq:config:reload", fmt.Sprintf("%d|%s", revision, name)).Err(); err != nil {
		return "notification_failed", "热重载通知失败；配置已保存，请恢复 Redis 后重试发布"
	}
	waitCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		state, err := a.redis.HGetAll(waitCtx, "mhq:config:runtime").Result()
		if err == nil {
			if parseInt64Param(state["revision"], 0) >= revision && state["status"] == "applied" {
				return "applied", "游戏服已确认加载配置"
			}
			if parseInt64Param(state["attemptedRevision"], 0) >= revision && state["status"] == "failed" {
				return "failed", "游戏服重载失败，仍使用旧运行快照：" + state["error"]
			}
		}
		select {
		case <-waitCtx.Done():
			return "pending", "配置已保存，等待游戏服确认加载"
		case <-ticker.C:
		}
	}
}
