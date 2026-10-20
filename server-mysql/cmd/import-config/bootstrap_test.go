package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestValidateDatatableRejectsMalformedAndDuplicateRows(t *testing.T) {
	for _, rows := range [][]interface{}{
		{}, {[]interface{}{int64(1)}}, {[]interface{}{int64(1), map[string]interface{}{}, true}},
		{[]interface{}{int64(1), "invalid"}}, {[]interface{}{true, map[string]interface{}{}}},
		{[]interface{}{int64(1), map[string]interface{}{}}, []interface{}{int64(1), map[string]interface{}{}}},
	} {
		if err := validateDatatable("test", rows); err == nil {
			t.Fatalf("accepted malformed rows: %#v", rows)
		}
	}
}

func TestConvertedYAMLPreservesLargeIntegersAndNestedTypes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "types.yaml")
	raw := "-\n  - 1\n  -\n    \"text\": \"true\"\n    \"flag\": true\n    \"large\": 9007199254740993\n    \"float\": 1.0\n    \"list\":\n      - null\n      - []\n      - {}\n"
	if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	value, err := decodeSourceFile(path)
	if err != nil {
		t.Fatal(err)
	}
	rows := value.([]interface{})
	if err := validateDatatable("types", rows); err != nil {
		t.Fatal(err)
	}
	fields := rows[0].([]interface{})[1].(map[string]interface{})
	if fields["large"] != int64(9007199254740993) || fields["float"] != float64(1) || fields["text"] != "true" || fields["flag"] != true {
		t.Fatalf("scalar types changed: %#v", fields)
	}
	list := fields["list"].([]interface{})
	if list[0] != nil || len(list[1].([]interface{})) != 0 || len(list[2].(map[string]interface{})) != 0 {
		t.Fatalf("nested values changed: %#v", list)
	}
}

func TestBootstrapMissingSourcesFailsBeforeDatabaseAccess(t *testing.T) {
	if err := runBootstrap(t.TempDir(), "", "invalid dsn", true); err == nil {
		t.Fatal("missing config accepted")
	}
}
