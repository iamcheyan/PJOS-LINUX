# Sourced in the image build container after extraction of the stock harvest.
  # Keep the prepared stock harvest pristine. Only remove GPU debug data from
  # this build copy, and fail rather than ship a changed module ABI/signature.
  GPU="$R/usr/lib/modules/mali_kbase.ko"
  [ -f "$GPU" ] || { echo "FATAL: missing harvested GPU module" >&2; exit 1; }
  python3 /build/strip_gpu_module.py "$GPU" "$GPU.strip-debug" \
    --report /work/gpu-strip-report.json
  mv "$GPU.strip-debug" "$GPU"
  # alsa-lib plugin dir: drop static/libtool litter
  rm -f "$R"/usr/lib/aarch64-linux-gnu/alsa-lib/*.a "$R"/usr/lib/aarch64-linux-gnu/alsa-lib/*.la
  # The build is mandatory: do not silently ship only its userspace loader.
  install -m 644 /work/audio-module/h700_speaker_amp.ko "$R/usr/lib/modules/h700_speaker_amp.ko"
  # Starts the USB host controllers that the boot files hold back; see rcS.
  install -m 644 /work/audio-module/h700_late_usb.ko "$R/usr/lib/modules/h700_late_usb.ko"

  # flat module paths used by rcS / setBluetooth.sh
  [ ! -f "$R/usr/lib/modules/4.9.170/kernel/drivers/net/wireless/rtl8821cs/8821cs.ko" ] \
    || ln -sf 4.9.170/kernel/drivers/net/wireless/rtl8821cs/8821cs.ko "$R/usr/lib/modules/8821cs.ko"
  [ ! -f "$R/usr/lib/modules/4.9.170/kernel/drivers/bluetooth/rtl_btlpm.ko" ] \
    || ln -sf 4.9.170/kernel/drivers/bluetooth/rtl_btlpm.ko "$R/usr/lib/modules/rtl_btlpm.ko"
