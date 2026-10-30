// Command keyboardd is the PJOS Universal Input Framework backend service.
// It serves the Input API over loopback HTTP and is safe to run standalone for
// Desktop Debug Mode (no full PJOS required).
//
// Env:
//   KEYBOARDD_ADDR  listen address (default 127.0.0.1:8787)
//   KEYBOARDD_DB    sqlite path (opt-in; requires -tags sqlite). Empty = in-memory.
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"pjos/keyboardd"
)

func main() {
	addr := os.Getenv("KEYBOARDD_ADDR")
	if addr == "" {
		addr = "127.0.0.1:8787"
	}

	// OpenStore resolves sqlite persistence under -tags sqlite; default returns
	// an in-memory store (nil). Building without the tag keeps keyboardd
	// dependency-free for dev/tests.
	store, err := keyboardd.OpenStore(os.Getenv("KEYBOARDD_DB"))
	if err != nil {
		log.Fatalf("keyboardd: store: %v", err)
	}
	if store != nil {
		defer store.Close()
	}

	mgr := keyboardd.New(store)
	srv := keyboardd.NewServer(mgr)

	httpSrv := &http.Server{Addr: addr, Handler: srv}
	go func() {
		log.Printf("keyboardd: listening on %s", addr)
		if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("keyboardd: serve: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	log.Printf("keyboardd: shutting down")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(ctx)
}
