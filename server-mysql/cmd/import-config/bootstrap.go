package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"mhqserver/internal/mysqlschema"
	"mhqserver/internal/operationsconfig"
)

type configSource struct {
	name  string
	value interface{}
	table bool
}

func validateDatatable(name string, rows []interface{}) error {
	if len(rows) == 0 {
		return fmt.Errorf("%s is empty", name)
	}
	seen := make(map[int64]bool)
	for i, raw := range rows {
		pair, ok := raw.([]interface{})
		if !ok || len(pair) != 2 {
			return fmt.Errorf("%s row %d: expected [id, object]", name, i)
		}
		id, err := numberInt(pair[0])
		if err != nil || id < 0 || id > 2147483647 || seen[id] {
			return fmt.Errorf("%s row %d: invalid or duplicate id %v", name, i, pair[0])
		}
		if _, ok := pair[1].(map[string]interface{}); !ok {
			return fmt.Errorf("%s row %d: value must be an object", name, i)
		}
		seen[id] = true
	}
	return nil
}

func loadBootstrapSources(dir, skill string) ([]configSource, string, error) {
	paths := make(map[string]string)
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, "", err
	}
	for _, entry := range entries {
		ext := strings.ToLower(filepath.Ext(entry.Name()))
		if entry.IsDir() || (ext != ".yaml" && ext != ".yml") {
			continue
		}
		name := strings.TrimSuffix(entry.Name(), filepath.Ext(entry.Name()))
		if paths[name] != "" {
			return nil, "", fmt.Errorf("duplicate YAML source %s", name)
		}
		paths[name] = filepath.Join(dir, entry.Name())
	}
	for _, name := range append(append([]string{}, datatableNames...), "Gameplay", "AffixWash") {
		if paths[name] == "" {
			return nil, "", fmt.Errorf("required YAML source missing: %s", name)
		}
	}
	if skill == "" {
		skill = filepath.Join(dir, "..", "SkillLogicConfig.yaml")
	}
	paths["SkillLogicConfig"] = skill
	names := make([]string, 0, len(paths))
	for name := range paths {
		names = append(names, name)
	}
	sort.Strings(names)
	hash := sha256.New()
	sources := make([]configSource, 0, len(names))
	for _, name := range names {
		value, err := decodeSourceFile(paths[name])
		if err != nil {
			return nil, "", fmt.Errorf("%s: %w", name, err)
		}
		table := true
		switch name {
		case "Gameplay":
			table = false
			_, err = operationsconfig.Decode(value)
		case "AffixWash":
			table = false
			_, err = operationsconfig.DecodeAffixWash(value)
		case "SkillLogicConfig":
			table = false
			obj, ok := value.(map[string]interface{})
			if !ok {
				err = fmt.Errorf("root must be an object")
			} else if skills, ok := obj["skillDic"].([]interface{}); !ok || len(skills) == 0 {
				err = fmt.Errorf("skillDic must not be empty")
			}
		default:
			rows, ok := value.([]interface{})
			if !ok {
				err = fmt.Errorf("root must be an array")
			} else {
				err = validateDatatable(name, rows)
			}
		}
		if err != nil {
			return nil, "", fmt.Errorf("%s: %w", name, err)
		}
		raw, err := os.ReadFile(paths[name])
		if err != nil {
			return nil, "", err
		}
		fmt.Fprintf(hash, "%s\x00%d\x00", name, len(raw))
		hash.Write(raw)
		sources = append(sources, configSource{name, value, table})
	}
	return sources, fmt.Sprintf("%x", hash.Sum(nil)), nil
}

func runBootstrap(dir, skill, dsn string, validateOnly bool) error {
	sources, version, err := loadBootstrapSources(dir, skill)
	if err != nil {
		return err
	}
	log.Printf("validated complete initial bundle: %d configurations sha256=%s", len(sources), version)
	if validateOnly {
		return nil
	}
	db, _, err := mysqlschema.Open(dsn)
	if err != nil {
		return err
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	conn, err := db.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()
	var locked int
	if err := conn.QueryRowContext(ctx, `SELECT GET_LOCK(CONCAT(DATABASE(), ':bootstrap'), 30)`).Scan(&locked); err != nil || locked != 1 {
		return fmt.Errorf("cannot acquire initialization lock: %v", err)
	}
	defer conn.ExecContext(context.Background(), `SELECT RELEASE_LOCK(CONCAT(DATABASE(), ':bootstrap'))`)
	if _, err := conn.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS game_bootstrap_state (id INT PRIMARY KEY, source_hash VARCHAR(64) NOT NULL, completed_at BIGINT NOT NULL)`); err != nil {
		return err
	}
	var previous string
	err = conn.QueryRowContext(ctx, `SELECT source_hash FROM game_bootstrap_state WHERE id = 1`).Scan(&previous)
	if err == nil {
		for _, name := range append(append([]string{}, datatableNames...), "SkillLogicConfig", "Gameplay", "AffixWash") {
			var count int
			if err := conn.QueryRowContext(ctx, `SELECT COUNT(*) FROM game_config_nodes WHERE config_name = ? AND parent_id = 0`, name).Scan(&count); err != nil {
				return err
			}
			if count == 0 {
				return fmt.Errorf("initialized database is missing %s; restore a backup or publish a reviewed configuration", name)
			}
		}
		log.Printf("initialization already completed (%s); keeping all existing data and published configuration", previous)
		return nil
	}
	if err != sql.ErrNoRows {
		return err
	}
	var count int
	if err := conn.QueryRowContext(ctx, `SELECT (SELECT COUNT(*) FROM game_config_nodes) + (SELECT COUNT(*) FROM accounts) + (SELECT COUNT(*) FROM players)`).Scan(&count); err != nil {
		return err
	}
	if count != 0 {
		return fmt.Errorf("database is not empty and has no bootstrap marker; refusing to overwrite existing data")
	}
	tx, err := conn.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, source := range sources {
		if source.table {
			for _, raw := range source.value.([]interface{}) {
				pair := raw.([]interface{})
				id, _ := numberInt(pair[0])
				if _, err := insertNode(tx, source.name, 0, "", int(id), pair[1]); err != nil {
					return fmt.Errorf("import %s: %w", source.name, err)
				}
			}
		} else if _, err := insertNode(tx, source.name, 0, "", -1, source.value); err != nil {
			return fmt.Errorf("import %s: %w", source.name, err)
		}
		log.Printf("prepared initial config %s", source.name)
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO game_config_revisions (published_at, publisher, note) VALUES (?, 'bootstrap', ?)`, time.Now().Unix(), "initial bundle sha256="+version); err != nil {
		return err
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO game_bootstrap_state VALUES (1, ?, ?)`, version, time.Now().Unix()); err != nil {
		return err
	}
	if err := tx.Commit(); err != nil {
		return err
	}
	log.Printf("initial configuration committed atomically: %d configurations", len(sources))
	return nil
}
