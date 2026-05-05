# Changelog

## 0.5.4

- Fix CLI `small_display` override handling.
- Fix custom band config validation.
- Clean up config test imports.
- ~~Derive CLI version dynamically.~~
- Keep default knob config without TOML entries.
- Clear band label when frequency is unavailable.
- Handle invalid log levels gracefully.
- Exit cleanly when keyboard input reaches EOF.
- Validate knob config entries.
- Remove stale input devices after invalid FD errors.
- Show quit message on Ctrl-C and EOF.

## 0.5.3
- Hardened reconnect scheduling and input-device cleanup.
- Made mouse discovery idempotent and safer with failing devices.
- Hardened custom band validation, sorting, overlap checks, and `goto` repair.
- Centralized iFreq Hz conversion and rounding.
- Hardened frequency logging and write-error handling.
- Corrected compact display option to `--small-display`.
- Hardened terminal display handling.
- Hardened RigCheck socket, stream, port, and stale-state handling.
- Device registration: Reject unknown devices

## 0.5.2
- Added automated test coverage:
  - Unit tests: config, bands, step, display formatting.
  - State-machine tests for `SyncManager`.
  - Fake TCP tests for Rig/Gqrx protocol behavior over localhost.
  - Input tests using fake keyboard/mouse/knob events.
  - Lifecycle tests for reconnect scheduling and device cleanup.
- Fixed iFreq Gqrx-only handling
- Fixed invalid TOML handling
- Improved device lifecycle handling

## 0.5.1
- Fixed iFreq GQRX-only tuning to send LNB_LO instead of normal frequency commands.
- Fixed small/full display toggle redraw state.
- Minor:
  - Improved rigctld command parsing with shlex and normalized configured TCP port handling.
  - Improved keyboard CSI escape sequence handling.
  - Improved mouse disconnect logging.
  - Updated README descriptions for iFreq and standalone mode behavior.

## 0.5.0
- Major internal refactoring of sync.py: simplified sync state and command/response handling.
- Improved socket reconnect, timeout, and stale-buffer handling.

## 0.4.4
- Added terminal resize detection and automatic display redraw.
- Improved startup and terminal cleanup robustness.
- Fixed daemon mode input device handling.
- Fixed split bracketed-paste sequence handling.
- Fixed band display to use main frequency.
- Improved device cleanup and scheduler shutdown order.
- Improved CAT command scheduling to avoid sending while busy.

## 0.4.3
- Improved cleanup, removed atexit
- Fixed input device FD leaks for mouse and knob scanning.
- Added bracketed paste handling to prevent pasted terminal text from triggering commands.
- Improved reconnect backoff by allowing tasks to report failure.

## 0.4.2
- Fixed frequency logging via -l/--log.
- Fixed delayed rig frequency logging and timestamps.
- Fixed configured band table usage and band display updates.
- Fixed pending nudge handling.
- Fixed shutdown/socket cleanup crashes.
- Improved malformed RPRT and rigcheck socket handling.
- Fixed reconnect scheduler TOML settings.
- Improved non-TTY startup and longer band labels.

## 0.4.1
- Added small display functionality
- Minor bug fixes
 
## 0.4.0
- Added Bands functionality

## 0.3.1
- Minor bug fixes
- Added thread-safety to `Display` (synchronized setters)  
- Eliminated UI flicker

## 0.3.0
- Initial release  