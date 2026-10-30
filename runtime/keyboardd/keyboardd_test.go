package keyboardd

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func newTestManager() (*Manager, *StubProvider) {
	stub := NewStubProvider()
	m := New(nil, stub) // nil store -> in-memory
	return m, stub
}

func TestShowValidatesLayout(t *testing.T) {
	m, _ := newTestManager()

	st, err := m.Show(ShowRequest{Layout: LayoutText})
	if err != nil {
		t.Fatalf("show text: %v", err)
	}
	if !st.Visible || st.Layout != LayoutText {
		t.Fatalf("unexpected state: %+v", st)
	}

	if _, err := m.Show(ShowRequest{Layout: "garbage"}); err == nil {
		t.Fatal("expected invalid_layout error")
	}
	if _, err := m.Show(ShowRequest{Layout: ""}); err == nil {
		t.Fatal("expected invalid_layout for empty")
	}
}

func TestShowRejectsReservedLayout(t *testing.T) {
	m, _ := newTestManager()
	for name := range ReservedLayouts {
		if _, err := m.Show(ShowRequest{Layout: Layout(name)}); err == nil {
			t.Fatalf("reserved layout %q should be rejected", name)
		} else if !strings.Contains(err.Error(), "layout_not_implemented") {
			t.Fatalf("reserved layout %q wrong error: %v", name, err)
		}
	}
}

func TestShowSetsSecureAndCapabilitiesAndInputMode(t *testing.T) {
	m, _ := newTestManager()
	st, err := m.Show(ShowRequest{
		Layout:       LayoutNumber,
		Secure:       true,
		Placeholder:  "PIN",
		Capabilities: []Capability{CapDPad, CapGamepad},
		Theme:        ThemeOLED,
	})
	if err != nil {
		t.Fatalf("show: %v", err)
	}
	if !st.Secure {
		t.Fatal("secure not set")
	}
	if st.Placeholder != "PIN" {
		t.Fatalf("placeholder: %q", st.Placeholder)
	}
	if st.InputMode != InputDPad {
		t.Fatalf("dpad capability should yield dpad mode, got %q", st.InputMode)
	}
	if st.Theme != ThemeOLED {
		t.Fatalf("theme: %q", st.Theme)
	}
}

func TestKeyCompositionAndControls(t *testing.T) {
	m, _ := newTestManager()
	if _, err := m.Show(ShowRequest{Layout: LayoutText}); err != nil {
		t.Fatal(err)
	}
	run := func(k string) {
		if _, err := m.Key(k); err != nil {
			t.Fatalf("key %q: %v", k, err)
		}
	}
	run("h")
	run("i")
	if st := m.State(); st.Value != "hi" {
		t.Fatalf("value: %q", st.Value)
	}
	run("space")
	run("A")
	if v := m.State().Value; v != "hi A" {
		t.Fatalf("value: %q", v)
	}
	run(KeyBackspace)
	if v := m.State().Value; v != "hi " {
		t.Fatalf("backspace value: %q", v)
	}
	run(KeyClear)
	if v := m.State().Value; v != "" {
		t.Fatalf("clear value: %q", v)
	}
}

func TestKeyRequiresVisible(t *testing.T) {
	m, _ := newTestManager()
	if _, err := m.Key("a"); err == nil {
		t.Fatal("expected keyboard_hidden error when not visible")
	}
}

func TestSubmitReturnsValueAndHides(t *testing.T) {
	m, _ := newTestManager()
	if _, err := m.Show(ShowRequest{Layout: LayoutText, Value: "pre"}); err != nil {
		t.Fatal(err)
	}
	_, _ = m.Key("x")
	v, st := m.Submit("")
	if v != "prex" {
		t.Fatalf("submit value: %q", v)
	}
	if st.Visible {
		t.Fatal("keyboard should be hidden after submit")
	}
	if st.Value != "" {
		t.Fatal("value should be cleared after submit")
	}
}

func TestFocusAutoShowsBlurAutoHides(t *testing.T) {
	m, _ := newTestManager()
	// not visible before focus
	if m.State().Visible {
		t.Fatal("should start hidden")
	}
	st, err := m.Focus("search", ShowRequest{Layout: LayoutText})
	if err != nil {
		t.Fatal(err)
	}
	if !st.Visible || st.FocusedInput != "search" {
		t.Fatalf("focus should auto-show: %+v", st)
	}
	// second focus stacks
	if _, err := m.Focus("other", ShowRequest{Layout: LayoutURL}); err != nil {
		t.Fatal(err)
	}
	// blur the top; still focused (search)
	st = m.Blur("other")
	if st.FocusedInput != "search" || !st.Visible {
		t.Fatalf("blur top should keep search focused+visible: %+v", st)
	}
	// blur search -> none focused -> hidden
	st = m.Blur("search")
	if st.Visible || st.FocusedInput != "" {
		t.Fatalf("blur last should auto-hide: %+v", st)
	}
}

func TestProviderSwitch(t *testing.T) {
	m, _ := newTestManager()
	if _, err := m.SetProvider("stub"); err != nil {
		t.Fatalf("set stub: %v", err)
	}
	if _, err := m.SetProvider("nope"); err == nil {
		t.Fatal("expected unknown_provider error")
	}
}

func TestProviderHooksFired(t *testing.T) {
	m, stub := newTestManager()
	_, _ = m.Show(ShowRequest{Layout: LayoutText})
	_, _ = m.Key("z")
	_, _ = m.Submit("")
	ev := stub.Events()
	kinds := []string{}
	for _, e := range ev {
		kinds = append(kinds, e.Kind)
	}
	if len(kinds) != 3 || kinds[0] != "show" || kinds[1] != "key" || kinds[2] != "submit" {
		t.Fatalf("provider hook order wrong: %v", kinds)
	}
}

func TestInputModeForNoHardcode(t *testing.T) {
	// capability-driven only; no device names involved
	cases := []struct {
		caps []Capability
		want InputMode
	}{
		{[]Capability{CapTouch}, InputTouch},
		{[]Capability{CapDPad}, InputDPad},
		{[]Capability{CapGamepad, CapDPad}, InputDPad},
		{[]Capability{CapHardwareKeyboard}, InputTouch},
		{[]Capability{}, InputTouch},
	}
	for _, c := range cases {
		if got := InputModeFor(c.caps); got != c.want {
			t.Fatalf("caps %v -> %q want %q", c.caps, got, c.want)
		}
	}
}

// --- API integration (stub provider, in-memory) ---

func newTestServer() (*httptest.Server, *StubProvider) {
	m, stub := newTestManager()
	return httptest.NewServer(NewServer(m)), stub
}

func TestAPIShowAndState(t *testing.T) {
	ts, _ := newTestServer()
	defer ts.Close()

	resp := post(t, ts, "/api/keyboard/show", `{"layout":"text","placeholder":"Search","capabilities":["Touch"]}`)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("show status %d", resp.StatusCode)
	}
	var body struct {
		State State `json:"state"`
	}
	json.Unmarshal(readBody(t, resp), &body)
	if !body.State.Visible || body.State.Layout != LayoutText || body.State.InputMode != InputTouch {
		t.Fatalf("show state: %+v", body.State)
	}

	// GET state round-trips
	g := get(t, ts, "/api/keyboard/state")
	var st State
	json.Unmarshal(readBody(t, g), &st)
	if st.Visible != true {
		t.Fatal("state visible mismatch")
	}
}

func TestAPIReservedLayout501(t *testing.T) {
	ts, _ := newTestServer()
	defer ts.Close()
	resp := post(t, ts, "/api/keyboard/show", `{"layout":"emoji"}`)
	if resp.StatusCode != http.StatusNotImplemented {
		t.Fatalf("expected 501, got %d", resp.StatusCode)
	}
}

func TestAPIKeyFlowThroughServer(t *testing.T) {
	ts, _ := newTestServer()
	defer ts.Close()
	post(t, ts, "/api/keyboard/show", `{"layout":"text"}`)
	post(t, ts, "/api/keyboard/key", `{"key":"h"}`)
	post(t, ts, "/api/keyboard/key", `{"key":"i"}`)
	resp := post(t, ts, "/api/keyboard/submit", `{}`)
	var body struct {
		Value string `json:"value"`
	}
	json.Unmarshal(readBody(t, resp), &body)
	if body.Value != "hi" {
		t.Fatalf("submit value via API: %q", body.Value)
	}
}

func TestAPIKeyWhenHidden409(t *testing.T) {
	ts, _ := newTestServer()
	defer ts.Close()
	resp := post(t, ts, "/api/keyboard/key", `{"key":"a"}`)
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("expected 409, got %d", resp.StatusCode)
	}
}

func TestAPIProvidersList(t *testing.T) {
	ts, _ := newTestServer()
	defer ts.Close()
	resp := get(t, ts, "/api/keyboard/providers")
	var body struct {
		Active    string         `json:"active"`
		Providers []ProviderInfo `json:"providers"`
	}
	json.Unmarshal(readBody(t, resp), &body)
	if body.Active != "stub" || len(body.Providers) == 0 {
		t.Fatalf("providers: %+v", body)
	}
}

// --- provider contract: Show/Hide/Render/Submit ---

func TestProviderRenderSpec(t *testing.T) {
	m, _ := newTestManager()
	if _, err := m.Show(ShowRequest{
		Layout:       LayoutURL,
		Placeholder:  "Address",
		Capabilities: []Capability{CapDPad},
		Theme:        ThemeOLED,
	}); err != nil {
		t.Fatal(err)
	}
	spec, provider := m.Render()
	if provider != "stub" {
		t.Fatalf("provider: %q", provider)
	}
	if spec.Layout != LayoutURL || spec.InputMode != InputDPad || spec.Theme != ThemeOLED {
		t.Fatalf("render spec: %+v", spec)
	}
	if !spec.Visible || spec.Placeholder != "Address" {
		t.Fatalf("render spec visibility/placeholder: %+v", spec)
	}
	if len(spec.Capabilities) != 1 || spec.Capabilities[0] != CapDPad {
		t.Fatalf("render spec capabilities: %v", spec.Capabilities)
	}
}

func TestProviderRenderReflectsHiddenState(t *testing.T) {
	m, _ := newTestManager()
	_, _ = m.Show(ShowRequest{Layout: LayoutText})
	if spec, _ := m.Render(); !spec.Visible {
		t.Fatal("expected visible spec")
	}
	m.Hide()
	if spec, _ := m.Render(); spec.Visible {
		t.Fatal("expected hidden spec after Hide")
	}
}

func TestProviderReceivesShowHideSubmit(t *testing.T) {
	// A provider that implements the full contract must observe Show/Hide/Submit
	// alongside the On* notifications.
	rec := &recordingProvider{}
	m := New(nil, rec)
	if _, err := m.Show(ShowRequest{Layout: LayoutNumber}); err != nil {
		t.Fatal(err)
	}
	m.SetProvider("recording")
	if _, err := m.Show(ShowRequest{Layout: LayoutText}); err != nil {
		t.Fatal(err)
	}
	_, _ = m.Key("7")
	m.Submit("")
	// Submit ends the composition directly; it does not detour through Hide.
	want := []string{"show", "onShow", "onKey", "submit", "onSubmit"}
	if len(rec.calls) != len(want) {
		t.Fatalf("calls: %v", rec.calls)
	}
	for i, w := range want {
		if rec.calls[i] != w {
			t.Fatalf("call %d = %q want %q (all: %v)", i, rec.calls[i], w, rec.calls)
		}
	}

	// Hide is observed when the keyboard is dismissed without submitting.
	_, _ = m.Show(ShowRequest{Layout: LayoutText})
	m.Hide()
	tail := rec.calls[len(rec.calls)-2:]
	if tail[0] != "hide" || tail[1] != "onHide" {
		t.Fatalf("hide notifications missing: %v", rec.calls)
	}
}

type recordingProvider struct{ calls []string }

func (p *recordingProvider) Name() string               { return "recording" }
func (p *recordingProvider) Capabilities() []Capability { return []Capability{CapTouch} }
func (p *recordingProvider) Show(req ShowRequest, st State) RenderSpec {
	p.calls = append(p.calls, "show")
	return specFromState(st)
}
func (p *recordingProvider) Hide(st State)                    { p.calls = append(p.calls, "hide") }
func (p *recordingProvider) Render(st State) RenderSpec       { return specFromState(st) }
func (p *recordingProvider) Submit(value string, st State)    { p.calls = append(p.calls, "submit") }
func (p *recordingProvider) OnShow(req ShowRequest, st State) { p.calls = append(p.calls, "onShow") }
func (p *recordingProvider) OnHide(st State)                  { p.calls = append(p.calls, "onHide") }
func (p *recordingProvider) OnKey(key string, st State)       { p.calls = append(p.calls, "onKey") }
func (p *recordingProvider) OnSubmit(value string, st State)  { p.calls = append(p.calls, "onSubmit") }

func TestAPIRenderEndpoint(t *testing.T) {
	ts, _ := newTestServer()
	defer ts.Close()

	post(t, ts, "/api/keyboard/show", `{"layout":"url","capabilities":["DPad"],"theme":"oled"}`)
	resp := get(t, ts, "/api/keyboard/render")
	var body struct {
		Provider string     `json:"provider"`
		Render   RenderSpec `json:"render"`
	}
	json.Unmarshal(readBody(t, resp), &body)
	if body.Provider != "stub" {
		t.Fatalf("provider: %q", body.Provider)
	}
	if body.Render.Layout != LayoutURL || body.Render.InputMode != InputDPad || body.Render.Theme != ThemeOLED {
		t.Fatalf("render: %+v", body.Render)
	}
}
