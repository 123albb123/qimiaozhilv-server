package main

import (
	"fmt"
	"strconv"
	"strings"

	json "github.com/goccy/go-json"
)

// Revision IDs cross the browser boundary as decimal strings to avoid
// JavaScript rounding a MySQL BIGINT. Numeric older clients remain supported.
type revisionInput int64

func (value *revisionInput) UnmarshalJSON(raw []byte) error {
	text := strings.TrimSpace(string(raw))
	if text == "null" {
		*value = 0
		return nil
	}
	if strings.HasPrefix(text, `"`) {
		if err := json.Unmarshal(raw, &text); err != nil {
			return err
		}
	}
	number, err := strconv.ParseInt(text, 10, 64)
	if err != nil || number < 0 {
		return fmt.Errorf("revision must be a non-negative BIGINT")
	}
	*value = revisionInput(number)
	return nil
}
