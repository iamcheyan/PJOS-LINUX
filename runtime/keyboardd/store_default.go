// Default (no build tag) store opener: in-memory. Persistence is opt-in under
// -tags sqlite; without the tag, requesting a DB path is an explicit error so
// the dependency surface stays pure standard library.
package keyboardd

import "fmt"

// OpenStore returns an in-memory store (nil) when path is empty; otherwise
// explains that sqlite persistence requires the build tag. Exported so the
// cmd binary can call it without build-tag coupling.
func OpenStore(path string) (Store, error) {
	return openStore(path)
}

// openStore returns an in-memory store when path is empty; otherwise explains
// that sqlite persistence requires the build tag.
func openStore(path string) (Store, error) {
	if path == "" {
		return nil, nil
	}
	return nil, fmt.Errorf("sqlite persistence requires building with -tags sqlite (got path %q)", path)
}
