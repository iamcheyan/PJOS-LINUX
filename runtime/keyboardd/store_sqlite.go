//go:build sqlite

// Package keyboardd optional persistence. Built only with -tags sqlite.
// Uses modernc.org/sqlite (pure Go, no cgo) for device capability profiles and
// last-state persistence. Phase 1 works without it (in-memory default).
package keyboardd

import (
	"database/sql"
	"encoding/json"

	_ "modernc.org/sqlite"
)

// SQLiteStore persists state under a single row key.
type SQLiteStore struct {
	db  *sql.DB
	key string
}

// NewSQLiteStore opens (or creates) the database and the state table.
func NewSQLiteStore(path string) (*SQLiteStore, error) {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	if _, err := db.Exec(`CREATE TABLE IF NOT EXISTS keyboard_state(
		k TEXT PRIMARY KEY, v TEXT NOT NULL)`); err != nil {
		db.Close()
		return nil, err
	}
	return &SQLiteStore{db: db, key: "state"}, nil
}

func (s *SQLiteStore) SaveState(st State) error {
	b, err := json.Marshal(st)
	if err != nil {
		return err
	}
	_, err = s.db.Exec(`INSERT INTO keyboard_state(k,v) VALUES(?,?)
		ON CONFLICT(k) DO UPDATE SET v=excluded.v`, s.key, string(b))
	return err
}

func (s *SQLiteStore) LoadState() (State, bool, error) {
	var v string
	err := s.db.QueryRow(`SELECT v FROM keyboard_state WHERE k=?`, s.key).Scan(&v)
	if err == sql.ErrNoRows {
		return State{}, false, nil
	}
	if err != nil {
		return State{}, false, err
	}
	var st State
	if err := json.Unmarshal([]byte(v), &st); err != nil {
		return State{}, false, err
	}
	return st, true, nil
}

func (s *SQLiteStore) Close() error { return s.db.Close() }

// openStore builds a SQLiteStore when path is non-empty (sqlite-tagged build).
func openStore(path string) (Store, error) {
	if path == "" {
		return nil, nil
	}
	return NewSQLiteStore(path)
}

// OpenStore builds a SQLiteStore when path is non-empty (sqlite-tagged build).
func OpenStore(path string) (Store, error) {
	return openStore(path)
}
