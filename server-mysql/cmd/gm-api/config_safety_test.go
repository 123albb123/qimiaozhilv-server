package main

import (
	"context"
	json "github.com/goccy/go-json"
	"testing"
	"unicode/utf8"
)

func TestConfigurationRejectsEmptyOrMalformedTreeBeforeOpeningDatabase(t *testing.T) {
	for _, raw := range []string{"[]", "- [1]", "- [1, {}]", "- [true, {Name: item}]", "- [1, {Name: a}]\n- [1, {Name: b}]", "- [1, {Name: a}, extra]"} {
		value, err := parseConfigYAML(raw)
		if err != nil {
			continue
		}
		if err := validateGMConfig("ShopBase", value); err == nil {
			t.Fatalf("accepted destructive configuration: %s", raw)
		}
		if _, err := replaceGMConfig(context.Background(), nil, "ShopBase", value, "test", "reject before SQL"); err == nil {
			t.Fatal("unsafe tree reached database path")
		}
	}
}

func TestDraftAcceptsStringRevisionWithoutLosingBIGINTPrecision(t *testing.T) {
	for _, raw := range []string{`{"baseRevision":"9007199254740993"}`, `{"baseRevision":9007199254740993}`} {
		var req configDraftRequest
		if err := json.Unmarshal([]byte(raw), &req); err != nil || req.BaseRevision != 9007199254740993 {
			t.Fatalf("revision was rejected or rounded: %s %v %d", raw, err, req.BaseRevision)
		}
	}
	for _, raw := range []string{`{"baseRevision":"-1"}`, `{"baseRevision":1.5}`, `{"baseRevision":"9223372036854775808"}`} {
		var req configDraftRequest
		if json.Unmarshal([]byte(raw), &req) == nil {
			t.Fatalf("invalid revision accepted: %s", raw)
		}
	}
}

func TestChineseAuditTruncationPreservesUTF8(t *testing.T) {
	for limit := 0; limit < 18; limit++ {
		got := truncate("中文备注测试", limit)
		if len(got) > limit || !utf8.ValidString(got) {
			t.Fatalf("invalid UTF-8 at limit %d: %q", limit, got)
		}
	}
}
