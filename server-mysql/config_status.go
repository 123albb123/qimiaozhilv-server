package main

import (
	"context"
	"log"
	"strconv"
	"sync"
	"time"
)

var configRuntimeReport struct {
	sync.RWMutex
	revision  int64
	attempted int64
	status    string
	errorText string
}

func writeConfigRuntimeStatus(ctx context.Context, cache *RedisCache) {
	if cache == nil || cache.client == nil {
		return
	}
	configRuntimeReport.RLock()
	values := map[string]any{"revision": strconv.FormatInt(configRuntimeReport.revision, 10), "attemptedRevision": strconv.FormatInt(configRuntimeReport.attempted, 10), "status": configRuntimeReport.status, "error": configRuntimeReport.errorText, "heartbeatAt": strconv.FormatInt(time.Now().Unix(), 10)}
	configRuntimeReport.RUnlock()
	publishCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	pipe := cache.client.TxPipeline()
	pipe.HSet(publishCtx, "mhq:config:runtime", values)
	pipe.Expire(publishCtx, "mhq:config:runtime", 90*time.Second)
	if _, err := pipe.Exec(publishCtx); err != nil && ctx.Err() == nil {
		log.Printf("config runtime status unavailable: %v", err)
	}
}

func recordConfigRuntimeStatus(ctx context.Context, cache *RedisCache, revision int64, err error) {
	configRuntimeReport.Lock()
	if revision < configRuntimeReport.attempted {
		configRuntimeReport.Unlock()
		return
	}
	configRuntimeReport.attempted = revision
	if err == nil {
		configRuntimeReport.revision = revision
		configRuntimeReport.status = "applied"
		configRuntimeReport.errorText = ""
	} else {
		configRuntimeReport.status = "failed"
		configRuntimeReport.errorText = err.Error()
	}
	configRuntimeReport.Unlock()
	writeConfigRuntimeStatus(ctx, cache)
}

func startConfigRuntimeReporter(ctx context.Context, cache *RedisCache, initialRevision int64) {
	recordConfigRuntimeStatus(ctx, cache, initialRevision, nil)
	go func() {
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				writeConfigRuntimeStatus(ctx, cache)
			}
		}
	}()
}
