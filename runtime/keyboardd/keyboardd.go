// Package keyboardd implements the PJOS Universal Input Framework backend:
// the Input API, Focus Manager, Provider Manager, layout validation, and a
// default in-process stub provider. It is pure Go (standard library only in the
// default build); state persistence via modernc.org/sqlite is opt-in under the
// "sqlite" build tag.
package keyboardd

import (
	"fmt"
	"sort"
	"strings"
	"sync"
)

// Layout is a keyboard layout name. Phase 1 implements text/number/url.
type Layout string

const (
	LayoutText   Layout = "text"
	LayoutNumber Layout = "number"
	LayoutURL    Layout = "url"
)

// Phase1Layouts are the layouts implemented in Phase 1.
var Phase1Layouts = map[Layout]bool{
	LayoutText:   true,
	LayoutNumber: true,
	LayoutURL:    true,
}

// ReservedLayouts are names reserved for future implementations
// (search/password/emoji/voice/ai). Phase 1 rejects them with 501.
var ReservedLayouts = map[Layout]bool{
	"search":   true,
	"password": true,
	"emoji":    true,
	"voice":    true,
	"ai":       true,
}

// Capability describes an available input hardware class. Selection is driven by
// capabilities, never by device-name strings.
type Capability string

const (
	CapTouch            Capability = "Touch"
	CapDPad             Capability = "DPad"
	CapGamepad          Capability = "Gamepad"
	CapHardwareKeyboard Capability = "HardwareKeyboard"
)

// AllCapabilities is the superset a provider may declare.
var AllCapabilities = []Capability{CapTouch, CapDPad, CapGamepad, CapHardwareKeyboard}

// InputMode is the keyboard navigation mode selected from capabilities.
type InputMode string

const (
	InputTouch InputMode = "touch"
	InputDPad  InputMode = "dpad"
)

// Theme is the keyboard color theme.
type Theme string

const (
	ThemeLight Theme = "light"
	ThemeDark  Theme = "dark"
	ThemeOLED  Theme = "oled"
)

// Phase1Themes are the supported themes in Phase 1.
var Phase1Themes = map[Theme]bool{ThemeLight: true, ThemeDark: true, ThemeOLED: true}

// State is the single source of truth for the on-screen keyboard.
type State struct {
	Visible      bool         `json:"visible"`
	Layout       Layout       `json:"layout"`
	Value        string       `json:"value"`
	Placeholder  string       `json:"placeholder"`
	Secure       bool         `json:"secure"`
	Capabilities []Capability `json:"capabilities"`
	InputMode    InputMode    `json:"inputMode"`
	FocusedInput string       `json:"focusedInput"`
	Provider     string       `json:"provider"`
	Theme        Theme        `json:"theme"`
}

// ShowRequest is the payload for show/focus requests.
type ShowRequest struct {
	Layout       Layout         `json:"layout"`
	Value        string         `json:"value"`
	Placeholder  string         `json:"placeholder"`
	Secure       bool           `json:"secure"`
	Capabilities []Capability   `json:"capabilities"`
	Theme        Theme          `json:"theme"`
	Options      map[string]any `json:"options"`
}

// KeyRequest injects a key/char into the active composition.
type KeyRequest struct {
	Key string `json:"key"`
}

// Control tokens accepted by Key (case-insensitive).
const (
	KeyBackspace = "backspace"
	KeySpace     = "space"
	KeyClear     = "clear"
	KeySwitch    = "layout:switch"
	KeyHide      = "hide"
)

// ProviderInfo describes a registered provider.
type ProviderInfo struct {
	Name         string       `json:"name"`
	Capabilities []Capability `json:"capabilities"`
}

// RenderSpec is what a provider needs to draw the keyboard. Returning it keeps
// Render free of side effects, so a headless provider can hand back a spec
// instead of driving a display.
type RenderSpec struct {
	Layout       Layout       `json:"layout"`
	InputMode    InputMode    `json:"inputMode"`
	Value        string       `json:"value"`
	Placeholder  string       `json:"placeholder"`
	Secure       bool         `json:"secure"`
	Capabilities []Capability `json:"capabilities"`
	Theme        Theme        `json:"theme"`
	Visible      bool         `json:"visible"`
	FocusedInput string       `json:"focusedInput"`
}

// KeyboardProvider is the provider contract from the framework design:
// Show/Hide/Render/Submit. Phase 1 ships a stub; pjos-keyboard is a remote
// provider that consumes the Input API. Future providers (Fcitx/Rime/Mozc/Voice)
// implement the same methods. The On* hooks are state-change notifications the
// Manager emits around those calls.
type KeyboardProvider interface {
	Name() string
	Capabilities() []Capability
	// Show makes the provider current and returns its render specification.
	Show(req ShowRequest, st State) RenderSpec
	// Hide tears the provider's presentation down.
	Hide(st State)
	// Render reports the current drawing without side effects.
	Render(st State) RenderSpec
	// Submit reports the composed value and releases the presentation.
	Submit(value string, st State)

	// State-change notifications (the provider is already active here).
	OnShow(req ShowRequest, st State)
	OnHide(st State)
	OnKey(key string, st State)
	OnSubmit(value string, st State)
}

// specFromState builds the provider-facing render specification.
func specFromState(st State) RenderSpec {
	return RenderSpec{
		Layout:       st.Layout,
		InputMode:    st.InputMode,
		Value:        st.Value,
		Placeholder:  st.Placeholder,
		Secure:       st.Secure,
		Capabilities: append([]Capability(nil), st.Capabilities...),
		Theme:        st.Theme,
		Visible:      st.Visible,
		FocusedInput: st.FocusedInput,
	}
}

// Store persists capability profiles and last state. Default is in-memory.
type Store interface {
	SaveState(st State) error
	LoadState() (State, bool, error)
	Close() error
}

// Manager owns state, providers, focus, and the Input API logic.
type Manager struct {
	mu         sync.Mutex
	state      State
	providers  map[string]KeyboardProvider
	active     string
	store      Store
	focusStack []string
}

// New creates a Manager with the given store (may be nil for in-memory only) and
// registers the supplied providers. If no provider is supplied, a stub is used.
func New(store Store, providers ...KeyboardProvider) *Manager {
	if store == nil {
		store = &memStore{}
	}
	m := &Manager{
		providers: map[string]KeyboardProvider{},
		store:     store,
		state: State{
			Capabilities: []Capability{},
			InputMode:    InputTouch,
			Provider:     "stub",
			Theme:        ThemeDark,
		},
	}
	all := append([]KeyboardProvider{NewStubProvider()}, providers...)
	for _, p := range all {
		m.providers[p.Name()] = p
	}
	if p, ok := m.providers["stub"]; ok {
		m.active = p.Name()
		m.state.Provider = p.Name()
	}
	if st, ok, _ := store.LoadState(); ok {
		st.Provider = m.active
		m.state = st
	}
	return m
}

// InputModeFor derives the navigation mode from capabilities (never device
// names). Touch wins; otherwise DPad; default Touch.
func InputModeFor(caps []Capability) InputMode {
	has := map[Capability]bool{}
	for _, c := range caps {
		has[c] = true
	}
	if has[CapTouch] {
		return InputTouch
	}
	if has[CapDPad] {
		return InputDPad
	}
	return InputTouch
}

// Show displays the keyboard with the given request.
func (m *Manager) Show(req ShowRequest) (State, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.validateLayout(req.Layout); err != nil {
		return m.state, err
	}
	m.applyShowLocked(req)
	return m.snapshot(), nil
}

// Focus sets the focused input and auto-shows the keyboard.
func (m *Manager) Focus(inputID string, req ShowRequest) (State, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.validateLayout(req.Layout); err != nil {
		return m.state, err
	}
	m.focusStack = append(m.focusStack, inputID)
	m.state.FocusedInput = inputID
	m.applyShowLocked(req)
	return m.snapshot(), nil
}

func (m *Manager) applyShowLocked(req ShowRequest) {
	m.state.Visible = true
	if req.Layout != "" {
		m.state.Layout = req.Layout
	}
	if req.Placeholder != "" || req.Layout != "" {
		m.state.Placeholder = req.Placeholder
	}
	if req.Secure {
		m.state.Secure = true
	}
	if len(req.Capabilities) > 0 {
		m.state.Capabilities = normalizeCaps(req.Capabilities)
		m.state.InputMode = InputModeFor(m.state.Capabilities)
	}
	if req.Theme != "" && Phase1Themes[req.Theme] {
		m.state.Theme = req.Theme
	}
	if req.Value != "" && m.state.Value == "" {
		m.state.Value = req.Value
	}
	m.notifyShow(req)
	m.persist()
}

// Blur clears focus for an input; if none remain focused, auto-hides.
func (m *Manager) Blur(inputID string) State {
	m.mu.Lock()
	defer m.mu.Unlock()
	if inputID != "" {
		out := m.focusStack[:0]
		for _, id := range m.focusStack {
			if id != inputID {
				out = append(out, id)
			}
		}
		m.focusStack = out
	}
	if len(m.focusStack) == 0 {
		m.state.FocusedInput = ""
		m.hideLocked()
	} else {
		m.state.FocusedInput = m.focusStack[len(m.focusStack)-1]
	}
	return m.snapshot()
}

// Hide hides the keyboard (keeps composed value until submit).
func (m *Manager) Hide() State {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.hideLocked()
	return m.snapshot()
}

func (m *Manager) hideLocked() {
	if !m.state.Visible {
		return
	}
	m.state.Visible = false
	m.notifyHide()
	m.persist()
}

// Submit returns the composed value, hides the keyboard, and clears focus.
func (m *Manager) Submit(override string) (string, State) {
	m.mu.Lock()
	defer m.mu.Unlock()
	value := m.state.Value
	if override != "" {
		value = override
		m.state.Value = override
	}
	m.notifySubmit(value)
	m.state.Visible = false
	m.state.Value = ""
	m.state.FocusedInput = ""
	m.focusStack = nil
	m.persist()
	return value, m.snapshot()
}

// Key injects a key/char. Printable chars are appended (case preserved); control
// tokens (case-insensitive) act.
func (m *Manager) Key(key string) (State, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.state.Visible {
		return m.state, fmt.Errorf("keyboard_hidden")
	}
	raw := strings.TrimSpace(key)
	token := strings.ToLower(raw)
	switch token {
	case KeyBackspace:
		m.state.Value = trimLastRune(m.state.Value)
	case KeySpace:
		m.state.Value += " "
	case KeyClear:
		m.state.Value = ""
	case KeySwitch:
		m.state.Layout = nextLayout(m.state.Layout)
	case KeyHide:
		m.hideLocked()
	default:
		if isPrintable(raw) {
			m.state.Value += raw
		} else {
			return m.state, fmt.Errorf("invalid_key: %q", key)
		}
	}
	m.notifyKey(key)
	m.persist()
	return m.snapshot(), nil
}

// Providers lists registered providers.
func (m *Manager) Providers() []ProviderInfo {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]ProviderInfo, 0, len(m.providers))
	for _, p := range m.providers {
		out = append(out, ProviderInfo{Name: p.Name(), Capabilities: p.Capabilities()})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

// Render returns the active provider's drawing specification.
func (m *Manager) Render() (RenderSpec, string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	st := m.snapshot()
	if p, ok := m.providers[m.active]; ok {
		return p.Render(st), p.Name()
	}
	return specFromState(st), m.active
}

// SetProvider switches the active provider.
func (m *Manager) SetProvider(name string) (State, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p, ok := m.providers[name]
	if !ok {
		return m.state, fmt.Errorf("unknown_provider: %s", name)
	}
	m.active = p.Name()
	m.state.Provider = p.Name()
	m.persist()
	return m.snapshot(), nil
}

// State returns a snapshot of the current state.
func (m *Manager) State() State {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.snapshot()
}

func (m *Manager) snapshot() State {
	s := m.state
	s.Capabilities = append([]Capability(nil), m.state.Capabilities...)
	return s
}

func (m *Manager) validateLayout(l Layout) error {
	if l == "" {
		return fmt.Errorf("invalid_layout: empty layout")
	}
	if Phase1Layouts[l] {
		return nil
	}
	if ReservedLayouts[l] {
		return fmt.Errorf("layout_not_implemented: %s", l)
	}
	return fmt.Errorf("invalid_layout: %s", l)
}

func (m *Manager) notifyShow(req ShowRequest) {
	if p, ok := m.providers[m.active]; ok {
		p.Show(req, m.snapshot())
		p.OnShow(req, m.snapshot())
	}
}
func (m *Manager) notifyHide() {
	if p, ok := m.providers[m.active]; ok {
		p.Hide(m.snapshot())
		p.OnHide(m.snapshot())
	}
}
func (m *Manager) notifyKey(key string) {
	if p, ok := m.providers[m.active]; ok {
		p.OnKey(key, m.snapshot())
	}
}
func (m *Manager) notifySubmit(value string) {
	if p, ok := m.providers[m.active]; ok {
		p.Submit(value, m.snapshot())
		p.OnSubmit(value, m.snapshot())
	}
}
func (m *Manager) persist() {
	if m.store != nil {
		_ = m.store.SaveState(m.snapshot())
	}
}

func normalizeCaps(caps []Capability) []Capability {
	seen := map[Capability]bool{}
	out := []Capability{}
	for _, c := range caps {
		if !seen[c] {
			seen[c] = true
			out = append(out, c)
		}
	}
	return out
}

func nextLayout(l Layout) Layout {
	switch l {
	case LayoutText:
		return LayoutNumber
	case LayoutNumber:
		return LayoutURL
	default:
		return LayoutText
	}
}

func trimLastRune(s string) string {
	r := []rune(s)
	if len(r) == 0 {
		return s
	}
	return string(r[:len(r)-1])
}

func isPrintable(s string) bool {
	if len(s) == 0 {
		return false
	}
	for _, r := range s {
		if r < 0x20 || r == 0x7f {
			return false
		}
	}
	return true
}
