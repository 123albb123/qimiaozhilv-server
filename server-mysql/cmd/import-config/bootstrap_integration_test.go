package main

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/go-sql-driver/mysql"
	"mhqserver/internal/mysqlschema"
)

func TestBootstrapMySQL(t *testing.T) {
	dsn, bundle := os.Getenv("MHQ_TEST_MYSQL_DSN"), os.Getenv("MHQ_TEST_BOOTSTRAP_DIR")
	if dsn == "" || bundle == "" {
		t.Skip("requires isolated MySQL and complete generated YAML bundle")
	}
	cfg, err := mysql.ParseDSN(dsn)
	if err != nil {
		t.Fatal(err)
	}
	cfg.DBName = fmt.Sprintf("mhq_test_bootstrap_%d_%d", os.Getpid(), time.Now().UnixNano())
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
	tables, skill := filepath.Join(bundle, "tables"), filepath.Join(bundle, "SkillLogicConfig.yaml")
	if err := runBootstrap(tables, skill, cfg.FormatDSN(), false); err != nil {
		t.Fatal(err)
	}
	var nodes, marker int64
	if err := db.QueryRow(`SELECT COUNT(*) FROM game_config_nodes`).Scan(&nodes); err != nil || nodes == 0 {
		t.Fatalf("nodes=%d err=%v", nodes, err)
	}
	if _, err := db.Exec(`UPDATE game_config_nodes SET string_value='bootstrap-persistence-test' WHERE config_name='GoodsBase' AND field_name='Name' LIMIT 1`); err != nil {
		t.Fatal(err)
	}
	if err := runBootstrap(tables, skill, cfg.FormatDSN(), false); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(`SELECT COUNT(*) FROM game_config_nodes WHERE string_value='bootstrap-persistence-test'`).Scan(&marker); err != nil || marker != 1 {
		t.Fatalf("repeat initialization overwrote published config: %d %v", marker, err)
	}
	var after int64
	if err := db.QueryRow(`SELECT COUNT(*) FROM game_config_nodes`).Scan(&after); err != nil || after != nodes {
		t.Fatalf("repeat initialization changed nodes: %d -> %d, %v", nodes, after, err)
	}
	if _, err := db.Exec(`DELETE FROM game_bootstrap_state`); err != nil {
		t.Fatal(err)
	}
	if err := runBootstrap(tables, skill, cfg.FormatDSN(), false); err == nil {
		t.Fatal("unmarked existing data was overwritten")
	}
	if err := db.QueryRow(`SELECT COUNT(*) FROM game_config_nodes WHERE string_value='bootstrap-persistence-test'`).Scan(&marker); err != nil || marker != 1 {
		t.Fatal("rejected initialization changed data")
	}
}
