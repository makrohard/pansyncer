# Changelog

## 0.4.3
- Removed atexit (no advantage over existing cleanup)
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