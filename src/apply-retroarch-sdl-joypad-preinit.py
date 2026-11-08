#!/usr/bin/env python3
"""Make RetroArch actually reach the pad on the RG34XX.

Three faults kept every button dead on this device:

1. `sdl_joypad_init` reads `SDL_WasInit(0)` before starting the joystick
   subsystem. The mali-fbdev video driver has already called
   `SDL_Init(SDL_INIT_VIDEO)`, so the flags are non-zero and the original code
   took the `SDL_InitSubSystem(GAMECONTROLLER)` branch. In this RetroArch
   build that call can fail while the video window is mid-creation, leaving
   `SDL_NumJoysticks()` at 0 — RetroArch then believes no pad exists.

   Start the subsystem unconditionally, and if no pads are visible retry once
   after a short settle: the device enumeration on this platform becomes
   reliable immediately after the window is live.

2. `sdl_joypad_poll` flushed events in the range
   `SDL_JOYAXISMOTION..SDL_CONTROLLERDEVICEREMAPPED`, which also covers every
   button, hat and controller-button event, so presses pumped in that frame
   were discarded before they were read.

3. The linuxraw joypad driver passes a NULL device name to autoconf, so the
   built-in pad can only be matched by VID/PID; the RetroArch core still needs
   a working joypad path. The sdl2 path is the reliable one here.

    python3 src/apply-retroarch-sdl-joypad-preinit.py <retroarch source tree>
"""
from pathlib import Path
import sys

JOYPAD_OLD = """   uint32_t sdl_subsystem_flags = SDL_WasInit(0);

   /* Initialise joystick/controller subsystem, if required */
   if (sdl_subsystem_flags == 0)
   {
      if (SDL_Init(subsystem) < 0)
         return NULL;
   }
   else if ((sdl_subsystem_flags & subsystem) == 0)
   {
      if (SDL_InitSubSystem(subsystem) < 0)
         return NULL;
   }"""

JOYPAD_NEW = """   uint32_t sdl_subsystem_flags = SDL_WasInit(0);

   /* Start the joystick subsystem unconditionally. The flags read before this
    * point are non-zero once the video driver has run, so the original branch
    * tried to add the subsystem during window creation and could fail silently,
    * leaving SDL_NumJoysticks() at zero. Retry once after a short settle — on
    * the RG34XX the pad is enumerated reliably once the window is live. */
   if (SDL_InitSubSystem(subsystem) < 0
         && (SDL_WasInit(0) & subsystem) == 0)
   {
      RARCH_ERR("[SDL]: Failed to start joystick subsystem: %s\\n",
            SDL_GetError());
      return NULL;
   }
   if (SDL_NumJoysticks() < 1)
   {
      /* The mali-fbdev window has just been created; give the device layer a
       * moment to settle, then retry the subsystem (and, as a last resort,
       * enumerate via the plain JOYSTICK subsystem — GC is a superset but this
       * build can expose the pad late). */
      SDL_Delay(200);
      SDL_QuitSubSystem(subsystem);
      SDL_InitSubSystem(subsystem);
      if (SDL_NumJoysticks() < 1)
      {
         SDL_InitSubSystem(SDL_INIT_JOYSTICK);
         SDL_InitSubSystem(subsystem);
      }
   }
   sdl_subsystem_flags = SDL_WasInit(0);
   RARCH_LOG("[SDL]: joystick subsystem ready; %d pad(s) detected.\\n",
         SDL_NumJoysticks());"""

FLUSH_OLD = "   SDL_FlushEvents(SDL_JOYAXISMOTION, SDL_CONTROLLERDEVICEREMAPPED);"
FLUSH_NEW = """   /* Only drop motion events. A range ending at SDL_CONTROLLERDEVICEREMAPPED
    * also swallows button/hat presses, which leaves the pad dead. */
   SDL_FlushEvent(SDL_JOYAXISMOTION);
   SDL_FlushEvent(SDL_JOYHATMOTION);"""


def patch(path: Path, old: str, new: str, marker: str, label: str) -> bool:
    text = path.read_text()
    if marker in text:
        print(f"already applied: {label}")
        return True
    if text.count(old) != 1:
        raise SystemExit(f"anchor for {label} appears {text.count(old)} times")
    path.write_text(text.replace(old, new, 1))
    print(f"applied {label}")
    return True


def main(tree: str) -> int:
    root = Path(tree)
    patch(root / "input/drivers_joypad/sdl_joypad.c", JOYPAD_OLD, JOYPAD_NEW,
          "joystick subsystem ready;", "unconditional joystick init with retry")
    patch(root / "input/drivers_joypad/sdl_joypad.c", FLUSH_OLD, FLUSH_NEW,
          "SDL_FlushEvent(SDL_JOYAXISMOTION);", "narrow event flush")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
