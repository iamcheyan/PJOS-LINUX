package keyboardd

import (
	"net/http"
	"testing"
)

// The keyboard provider runs on a different origin (Vite dev server, PocketJS
// host, shell page), so JSON POSTs are preflighted. The API must answer the
// preflight and advertise the CORS headers on real responses.
func TestCORSPreflight(t *testing.T) {
	ts, _ := newTestServer()
	defer ts.Close()

	req, err := http.NewRequest(http.MethodOptions, ts.URL+"/api/keyboard/show", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Origin", "http://127.0.0.1:5299")
	req.Header.Set("Access-Control-Request-Method", "POST")
	req.Header.Set("Access-Control-Request-Headers", "content-type")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("preflight status: %d", resp.StatusCode)
	}
	if got := resp.Header.Get("Access-Control-Allow-Origin"); got != "*" {
		t.Fatalf("allow-origin: %q", got)
	}
	if got := resp.Header.Get("Access-Control-Allow-Methods"); got == "" {
		t.Fatal("allow-methods missing")
	}
	if got := resp.Header.Get("Access-Control-Allow-Headers"); got == "" {
		t.Fatal("allow-headers missing")
	}
}

func TestCORSHeadersOnPost(t *testing.T) {
	ts, _ := newTestServer()
	defer ts.Close()

	resp := post(t, ts, "/api/keyboard/show", `{"layout":"text"}`)
	defer resp.Body.Close()
	if got := resp.Header.Get("Access-Control-Allow-Origin"); got != "*" {
		t.Fatalf("allow-origin on POST: %q", got)
	}
}
