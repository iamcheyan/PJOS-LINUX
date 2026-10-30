package keyboardd

import (
	"encoding/json"
	"net/http"
)

// Server exposes the Input API over HTTP (loopback). The frontend provider and
// applications both talk to these endpoints.
type Server struct {
	mgr *Manager
	mux *http.ServeMux
}

// NewServer builds an HTTP server from a Manager.
func NewServer(mgr *Manager) *Server {
	s := &Server{mgr: mgr, mux: http.NewServeMux()}
	s.routes()
	return s
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) { s.mux.ServeHTTP(w, r) }

func (s *Server) routes() {
	s.mux.HandleFunc("/api/health", s.health)
	s.mux.HandleFunc("/api/keyboard/show", s.show)
	s.mux.HandleFunc("/api/keyboard/hide", s.hide)
	s.mux.HandleFunc("/api/keyboard/submit", s.submit)
	s.mux.HandleFunc("/api/keyboard/focus", s.focus)
	s.mux.HandleFunc("/api/keyboard/blur", s.blur)
	s.mux.HandleFunc("/api/keyboard/key", s.key)
	s.mux.HandleFunc("/api/keyboard/state", s.state)
	s.mux.HandleFunc("/api/keyboard/providers", s.providers)
	s.mux.HandleFunc("/api/keyboard/provider", s.setProvider)
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	jsonOut(w, http.StatusOK, map[string]any{"status": "ok", "service": "keyboardd", "version": "0.1.0"})
}

func (s *Server) show(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		fail(w, http.StatusMethodNotAllowed, "method_not_allowed", "POST required")
		return
	}
	var req ShowRequest
	if err := decode(r, &req); err != nil {
		fail(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	st, err := s.mgr.Show(req)
	if err != nil {
		apiErr(w, err)
		return
	}
	jsonOut(w, http.StatusOK, map[string]any{"state": st})
}

func (s *Server) focus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		fail(w, http.StatusMethodNotAllowed, "method_not_allowed", "POST required")
		return
	}
	var req struct {
		InputID      string      `json:"inputId"`
		ShowRequest
	}
	if err := decode(r, &req); err != nil {
		fail(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	st, err := s.mgr.Focus(req.InputID, req.ShowRequest)
	if err != nil {
		apiErr(w, err)
		return
	}
	jsonOut(w, http.StatusOK, map[string]any{"state": st})
}

func (s *Server) blur(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		fail(w, http.StatusMethodNotAllowed, "method_not_allowed", "POST required")
		return
	}
	var req struct {
		InputID string `json:"inputId"`
	}
	_ = decode(r, &req)
	st := s.mgr.Blur(req.InputID)
	jsonOut(w, http.StatusOK, map[string]any{"state": st})
}

func (s *Server) hide(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		fail(w, http.StatusMethodNotAllowed, "method_not_allowed", "POST required")
		return
	}
	st := s.mgr.Hide()
	jsonOut(w, http.StatusOK, map[string]any{"state": st})
}

func (s *Server) submit(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		fail(w, http.StatusMethodNotAllowed, "method_not_allowed", "POST required")
		return
	}
	var req struct {
		Value string `json:"value"`
	}
	_ = decode(r, &req)
	value, st := s.mgr.Submit(req.Value)
	jsonOut(w, http.StatusOK, map[string]any{"value": value, "state": st})
}

func (s *Server) key(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		fail(w, http.StatusMethodNotAllowed, "method_not_allowed", "POST required")
		return
	}
	var req KeyRequest
	if err := decode(r, &req); err != nil {
		fail(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	st, err := s.mgr.Key(req.Key)
	if err != nil {
		apiErr(w, err)
		return
	}
	jsonOut(w, http.StatusOK, map[string]any{"state": st})
}

func (s *Server) state(w http.ResponseWriter, r *http.Request) {
	jsonOut(w, http.StatusOK, s.mgr.State())
}

func (s *Server) providers(w http.ResponseWriter, r *http.Request) {
	jsonOut(w, http.StatusOK, map[string]any{
		"active":    s.mgr.State().Provider,
		"providers": s.mgr.Providers(),
	})
}

func (s *Server) setProvider(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		fail(w, http.StatusMethodNotAllowed, "method_not_allowed", "POST required")
		return
	}
	var req struct {
		Name string `json:"name"`
	}
	if err := decode(r, &req); err != nil {
		fail(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	st, err := s.mgr.SetProvider(req.Name)
	if err != nil {
		apiErr(w, err)
		return
	}
	jsonOut(w, http.StatusOK, map[string]any{"state": st})
}

// apiErr maps Manager errors to HTTP codes.
func apiErr(w http.ResponseWriter, err error) {
	msg := err.Error()
	switch {
	case startsWith(msg, "invalid_layout"):
		fail(w, http.StatusBadRequest, "invalid_layout", msg)
	case startsWith(msg, "layout_not_implemented"):
		fail(w, http.StatusNotImplemented, "layout_not_implemented", msg)
	case startsWith(msg, "unknown_provider"):
		fail(w, http.StatusNotFound, "unknown_provider", msg)
	case startsWith(msg, "keyboard_hidden"):
		fail(w, http.StatusConflict, "keyboard_hidden", msg)
	default:
		fail(w, http.StatusBadRequest, "bad_request", msg)
	}
}

func decode(r *http.Request, v any) error {
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	return d.Decode(v)
}

func jsonOut(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, status int, code, msg string) {
	jsonOut(w, status, map[string]any{"error": map[string]string{"code": code, "message": msg}})
}

func startsWith(s, p string) bool {
	return len(s) >= len(p) && s[:len(p)] == p
}
