# Shared PocketJS keyboard (2026-11-13)

PocketShell's Wi-Fi passphrase and Kanade's NAS settings both use the existing
`@pocketjs/framework/osk` controller and `<Osk>` view. The framework already
owns text editing, caret, shift/symbol layers, focus, d-pad navigation, button
chords and modal input blocking. This pass adds one reusable `pjos` skin to that
component: square keys with the same purple, gold and pixel-font palette as the
240×160 launcher and player. Each app still owns its field value and submit
action, so a rejected Wi-Fi passphrase can stay open while a saved NAS field
can close on commit.

The source patch is [apply-pocketjs-pjos-osk-theme.py](../src/apply-pocketjs-pjos-osk-theme.py).
Both PocketShell and Kanade build scripts apply it idempotently to their shared
SDK before check/compile. Other PJOS PocketJS apps can do the same, then use:

```tsx
import { createSignal } from "solid-js";
import { createOsk, Osk } from "@pocketjs/framework/osk";

const [value, setValue] = createSignal("");
const keyboard = createOsk({
  value,
  setValue,
  onCommit: (text) => { /* call the app's save action with text */ },
  closeOnCommit: true,
});

// Open from a field's A/confirm handler; dock the view at the screen bottom.
keyboard.open();
<Osk osk={keyboard} theme="pjos" />;
```

When an app reads raw `onFrame` button bits, it should let the keyboard own
them while `keyboard.isOpen()` is true. `createOsk` itself handles text events
and the framework's focus/button handlers. Password fields should keep their
value in app state and mask only the displayed row; the keyboard edits the real
buffer. The app chooses its own length limit, commit result and cancel action.

Verification: the patch was applied twice to a clean SDK copy with identical
hashes, and both apps passed SDK TypeScript check and package compile.
PocketShell's 10 Bun tests and the framework's 27 OSK tests passed. No simulator
or device keyboard acceptance was performed in this pass.

As of 2026-11-13 the patch also sets `pjos` as the SDK-wide default theme for
`<Osk>`, `TextField` and `oskHeight()`. An app that passes an explicit theme
still gets exactly that theme; only un-themed call sites pick up the PJOS skin.
Both apps were rebuilt after this change:

- PocketShell: `c1c2d5620c0415ec13282feb5046a5646907bdcc16528e64fa04022186d5b845`
- Kanade: `28cf7ab03519b1accbc0ecd1b4d321789028bbf9cbb5b7ba6f09aebbee32a1a8`
