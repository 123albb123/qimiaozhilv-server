// Offline bridge for the independently backed-up Unity shop compatibility pack.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"gopkg.in/yaml.v3"
	"os"
	"path/filepath"
	"sort"
)

func main() {
	source := flag.String("source", "config/operations", "editable YAML source")
	output := flag.String("output", "", "new output directory")
	flag.Parse()
	if *output == "" {
		panic("output is required")
	}
	if err := os.Mkdir(*output, 0700); err != nil {
		panic(err)
	}
	for _, name := range []string{"MarketBase", "ShopBase"} {
		raw, err := os.ReadFile(filepath.Join(*source, name+".yaml"))
		if err != nil {
			panic(err)
		}
		var rows [][]interface{}
		if err = yaml.Unmarshal(raw, &rows); err != nil {
			panic(err)
		}
		sort.Slice(rows, func(i, j int) bool { return rows[i][0].(int) < rows[j][0].(int) })
		encoded, err := json.MarshalIndent(rows, "", "  ")
		if err != nil {
			panic(err)
		}
		if err = os.WriteFile(filepath.Join(*output, name+".json"), encoded, 0600); err != nil {
			panic(err)
		}
		fmt.Printf("%s: %d rows exported for offline client adaptation\n", name, len(rows))
	}
}
