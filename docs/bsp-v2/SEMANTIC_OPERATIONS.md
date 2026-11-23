# Semantic operation implementation notes

`baseosctl` returns `0` for success, `2` for invalid arguments, `3` for unavailable or unknown, and `4` for explicitly unsupported operations. Hardware operations read the composed profile; they do not infer capability from a node name or invoke a vendor command selected by product identity.

## Input key state

`input key-state <role> <KEY_NAME|CODE>` resolves the role with the board profile's input name match, then invokes the static `/usr/sbin/baseos-input-state` helper with that resolved node. The helper queries `EVIOCGBIT(EV_KEY)` to confirm support and `EVIOCGKEY` for current state. It prints `pressed=0|1`; malformed key values return `2`, unavailable ioctl/node/key support returns `3`. Numeric codes accept decimal or `0x` hexadecimal; symbolic names are Linux `KEY_*`/`BTN_*` names supported by the helper. No event index is assumed.

## Projected profile fields for auxiliary operations

`tools/bsp_compose.py` projects scalar node and board values into `profile.env` as `<group>.<field>`; capabilities and features become `cap.<name>` and `feature.<name>`. Hook paths must be absolute executable paths supplied by an explicitly selected and validated adapter. Recommended fields:

- Network: `network.wifi_iface`, `network.bt_hook`, `network.mdns_hook`; tri-state `cap.wifi` and `cap.bluetooth`. `wifi-scan` normalizes `iw dev <profile-interface> scan` into one `ssid=... signal=... security=...` line per nonempty SSID. `bt_hook` receives `bt-up` or `bt-down`; `mdns_hook` receives `refresh <interface>`. No interface is embedded in the operation.
- Storage: `storage.layout`, `storage.boot_disk`, `storage.role.<role>`, `feature.storage_expand`, `storage.expand_hook`, `feature.storage_card_mount`, `storage.card-mount_hook`. Expansion and card mounting dispatch only to the explicit hook after its feature is `yes`. Without a validated adapter, callers receive `3`. An adapter must identify its target role, inspect mount, partition and filesystem state, refuse occupied or ambiguous media, and must not format arbitrary media. A profile claiming `yes` needs driver and fake-tree evidence for these checks.
- LEDs/haptics: `led.work_node`, `led.vibration_node`; haptic duration is written in milliseconds to the declared node. `cap.vibration` gates vibration; `unknown` returns `3`, `no` returns `4`. Current H700 and TG5040 profiles declare vibration `unknown`, so neither is asserted to have a motor node or known duration ABI.

## Required driver evidence

For H700, `bsp/allwinner/h700/soc.json` declares `wlan0` and `rtl8821cs-h5`, but does not provide safe Bluetooth control and mDNS hooks or storage expand/card-mount adapters. Keep those paths unavailable until concrete hooks exist and are tested. For A133/TG5040, the audit establishes interface names `wlan0` and `wlan1` only; it does not establish which interface is Wi-Fi, its driver/firmware, Bluetooth backend, storage layout or safe expansion procedure. Do not promote these facts from interface presence or a product name. No motor node or haptic ABI is established either.

Additional scalar metadata the profile compiler should project when adapters are authored: `network.mdns_hook`, `network.bt_hook`, `storage.expand_hook`, `storage.card-mount_hook`, `led.vibration_node`, and feature tri-states `storage_expand` and `storage_card_mount`. The existing schema rejects such adapter fields until matching definitions are added; current profiles therefore remain unknown/unavailable rather than receiving guessed H700/A133 values.
