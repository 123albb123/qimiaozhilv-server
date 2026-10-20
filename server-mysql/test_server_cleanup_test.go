package main

import "testing"

// Tests constructing Server literals still own asynchronous map/AI/vital
// callbacks. Invalidate those sessions before restoring package-wide fixtures.
func cleanupGameTestServer(t *testing.T, server *Server) {
	t.Helper()
	t.Cleanup(func() {
		server.closed.Store(true)
		for _, ch := range server.onlineChannels() {
			ch.session.superseded.Store(true)
			ch.session.stopMainStoryAI()
			ch.session.markMapChange()
			ch.teamHeadReloadGen.Add(1)
		}
		// An already-running scene callback must finish before fixtures change.
		server.mapTransitionMu.Lock()
		server.mapTransitionMu.Unlock()
	})
}
