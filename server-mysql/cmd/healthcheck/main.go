// healthcheck is shared by minimal runtime images; no shell is required.
package main

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"time"
)

func main() {
	if len(os.Args) != 3 {
		os.Exit(2)
	}
	var err error
	if os.Args[1] == "tcp" {
		var conn net.Conn
		conn, err = net.DialTimeout("tcp", os.Args[2], 2*time.Second)
		if conn != nil {
			conn.Close()
		}
	} else if os.Args[1] == "http" {
		var response *http.Response
		response, err = (&http.Client{Timeout: 5 * time.Second}).Get(os.Args[2])
		if response != nil {
			response.Body.Close()
			if response.StatusCode != http.StatusOK {
				err = fmt.Errorf("HTTP %d", response.StatusCode)
			}
		}
	} else {
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
