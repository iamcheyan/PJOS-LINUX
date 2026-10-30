package keyboardd

// StubProvider is the default in-process provider used for headless/desktop
// development and tests. It records hooks so tests can assert that show/hide/
// key/submit reached the active provider, and it declares the full capability
// superset so the Input API works with any device profile.
type StubProvider struct {
	events []ProviderEvent
}

// ProviderEvent is a recorded provider hook invocation.
type ProviderEvent struct {
	Kind   string `json:"kind"` // show|hide|key|submit
	Key    string `json:"key,omitempty"`
	Value  string `json:"value,omitempty"`
	Layout Layout `json:"layout,omitempty"`
}

// NewStubProvider returns a stub provider named "stub".
func NewStubProvider() *StubProvider {
	return &StubProvider{}
}

func (p *StubProvider) Name() string { return "stub" }

func (p *StubProvider) Capabilities() []Capability { return AllCapabilities }

func (p *StubProvider) OnShow(req ShowRequest, st State) {
	p.events = append(p.events, ProviderEvent{Kind: "show", Layout: req.Layout})
}

func (p *StubProvider) OnHide(st State) {
	p.events = append(p.events, ProviderEvent{Kind: "hide"})
}

func (p *StubProvider) OnKey(key string, st State) {
	p.events = append(p.events, ProviderEvent{Kind: "key", Key: key, Value: st.Value})
}

func (p *StubProvider) OnSubmit(value string, st State) {
	p.events = append(p.events, ProviderEvent{Kind: "submit", Value: value})
}

// Events returns a copy of recorded events (for tests/inspection).
func (p *StubProvider) Events() []ProviderEvent {
	out := make([]ProviderEvent, len(p.events))
	copy(out, p.events)
	return out
}

// memStore is the default in-memory Store. Safe for dev/tests.
type memStore struct {
	st  State
	set bool
}

func (s *memStore) SaveState(st State) error {
	s.st = st
	s.set = true
	return nil
}

func (s *memStore) LoadState() (State, bool, error) {
	return s.st, s.set, nil
}

func (s *memStore) Close() error { return nil }
