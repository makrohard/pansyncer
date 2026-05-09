"""
PanSyncer input-device test lab. Creates fake Linux uinput input devices and exposes a netcat-compatible control socket.
"""

import argparse
import os
import random
import socket
import sys
import threading
import time
from contextlib import suppress

try:
    from evdev import UInput, ecodes as e
    from evdev.uinput import UInputError
except ImportError as exc:
    raise SystemExit("Missing dependency: python-evdev / evdev") from exc


DEFAULT_CONTROL_PORT = 4537
DEFAULT_INTERVAL_MS = 0

KNOB_NAME = "PanSyncer Fake VFO Knob"
KNOB_VENDOR = 0x1234
KNOB_PRODUCT = 0x5678

MOUSE_NAME = "PanSyncer Fake Mouse"
MOUSE_VENDOR = 0x1234
MOUSE_PRODUCT = 0x5679


def format_uinput_error(exc, control_port):
    return (
        f"error: cannot create fake input device: {exc}\n"
        "\n"
        "Fix one of:\n"
        "  sudo modprobe uinput\n"
        f"  sudo .venv/bin/python testlab/fake_inputs.py --control-port {control_port}\n"
        "\n"
        "Or configure non-root access to /dev/uinput as described in testlab/README.md.\n"
    )


class FakeKnob:
    def __init__(self):
        self._lock = threading.RLock()
        self._ui = None
        self.press_time = 0.01
        self._spin_stop = threading.Event()
        self._spin_thread = None
        self._spin_mode = None

    def plug(self):
        with self._lock:
            if self._ui is not None:
                return "knob: already plugged\n"

            capabilities = {
                e.EV_KEY: [
                    e.KEY_VOLUMEUP,
                    e.KEY_VOLUMEDOWN,
                    e.KEY_MUTE,
                ]
            }

            self._ui = UInput(
                capabilities,
                name=KNOB_NAME,
                vendor=KNOB_VENDOR,
                product=KNOB_PRODUCT,
                version=0x0001,
                bustype=e.BUS_USB,
            )

        time.sleep(0.2)
        return "knob: plugged\n"

    def unplug(self):
        self.spin_stop()

        with self._lock:
            ui = self._ui
            self._ui = None

        if ui is None:
            return "knob: already unplugged\n"

        with suppress(Exception):
            ui.close()

        time.sleep(0.2)
        return "knob: unplugged\n"

    def cycle(self):
        msg = self.unplug()
        time.sleep(0.2)
        msg += self.plug()
        return msg

    def status(self):
        with self._lock:
            plugged = self._ui is not None

        return (
            "Knob:\n"
            f"  device:          {'PLUGGED' if plugged else 'UNPLUGGED'}\n"
            f"  spin:            {self._spin_state().upper()}\n"
            f"  name:            {KNOB_NAME}\n"
            f"  vendor:          0x{KNOB_VENDOR:04x}\n"
            f"  product:         0x{KNOB_PRODUCT:04x}\n"
            f"  key_up:          {e.KEY_VOLUMEUP}\n"
            f"  key_down:        {e.KEY_VOLUMEDOWN}\n"
            f"  key_step:        {e.KEY_MUTE}\n"
        )

    def up(self):
        self._key(e.KEY_VOLUMEUP)
        return "knob: up\n"

    def down(self):
        self._key(e.KEY_VOLUMEDOWN)
        return "knob: down\n"

    def click(self):
        self._key(e.KEY_MUTE)
        return "knob: click\n"

    def flood(self, count, interval_ms=DEFAULT_INTERVAL_MS):
        count = int(count)
        key = e.KEY_VOLUMEUP if count >= 0 else e.KEY_VOLUMEDOWN
        self._flood(key, abs(count), interval_ms)
        return f"knob: flood count={count} interval_ms={interval_ms}\n"

    def spin_start(self, mode="start"):
        if mode not in ("start", "fast"):
            raise ValueError("expected start|fast")

        self.spin_stop()

        with self._lock:
            if self._ui is None:
                raise RuntimeError("knob is unplugged")

            self._spin_stop.clear()
            self._spin_mode = mode
            self._spin_thread = threading.Thread(target=self._spin_loop, args=(mode,), daemon=True)
            self._spin_thread.start()

        return f"knob: spin={mode}\n"

    def spin_stop(self):
        with self._lock:
            thread = self._spin_thread
            self._spin_stop.set()

        if thread is not None:
            thread.join(timeout=1.0)

        with self._lock:
            if self._spin_thread is thread:
                self._spin_thread = None
            self._spin_mode = None

        return "knob: spin=off\n"

    def spin_status(self):
        return f"knob: spin={self._spin_state()}\n"

    def _spin_state(self):
        with self._lock:
            if self._spin_thread is not None and self._spin_thread.is_alive():
                return self._spin_mode or "on"
            return "off"

    def _spin_loop(self, mode):
        try:
            while not self._spin_stop.is_set():
                key = random.choice((e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN))

                if mode == "fast":
                    run_seconds = random.uniform(0.2, 0.8)
                    interval = random.uniform(0.001, 0.02)
                else:
                    run_seconds = random.uniform(1.5, 5.0)
                    interval = random.uniform(0.04, 0.35)

                end_time = time.monotonic() + run_seconds

                while time.monotonic() < end_time and not self._spin_stop.is_set():
                    try:
                        self._key(key)
                    except RuntimeError:
                        return
                    time.sleep(interval)
        finally:
            with self._lock:
                self._spin_thread = None
                self._spin_mode = None
                self._spin_stop.set()

    def _key(self, key):
        with self._lock:
            ui = self._ui

        if ui is None:
            raise RuntimeError("knob is unplugged")

        ui.write(e.EV_KEY, key, 1)
        ui.syn()
        time.sleep(self.press_time)
        ui.write(e.EV_KEY, key, 0)
        ui.syn()

    def _flood(self, key, count, interval_ms):
        interval = max(0.0, float(interval_ms) / 1000.0)

        for _ in range(int(count)):
            self._key(key)
            if interval:
                time.sleep(interval)


class FakeMouse:
    BUTTONS = {
        "left": e.BTN_LEFT,
        "middle": e.BTN_MIDDLE,
        "right": e.BTN_RIGHT,
    }

    def __init__(self):
        self._lock = threading.RLock()
        self._ui = None
        self.press_time = 0.01
        self._wheel_spin_stop = threading.Event()
        self._wheel_spin_thread = None
        self._wheel_spin_mode = None

    def plug(self):
        with self._lock:
            if self._ui is not None:
                return "mouse: already plugged\n"

            capabilities = {
                e.EV_KEY: [
                    e.BTN_LEFT,
                    e.BTN_MIDDLE,
                    e.BTN_RIGHT,
                ],
                e.EV_REL: [
                    e.REL_X,
                    e.REL_Y,
                    e.REL_WHEEL,
                ],
            }

            self._ui = UInput(
                capabilities,
                name=MOUSE_NAME,
                vendor=MOUSE_VENDOR,
                product=MOUSE_PRODUCT,
                version=0x0001,
                bustype=e.BUS_USB,
            )

        time.sleep(0.2)
        return "mouse: plugged\n"

    def unplug(self):
        self.wheel_spin_stop()

        with self._lock:
            ui = self._ui
            self._ui = None

        if ui is None:
            return "mouse: already unplugged\n"

        with suppress(Exception):
            ui.close()

        time.sleep(0.2)
        return "mouse: unplugged\n"

    def cycle(self):
        msg = self.unplug()
        time.sleep(0.2)
        msg += self.plug()
        return msg

    def status(self):
        with self._lock:
            plugged = self._ui is not None

        return (
            "Mouse:\n"
            f"  device:          {'PLUGGED' if plugged else 'UNPLUGGED'}\n"
            f"  wheel spin:      {self._wheel_spin_state().upper()}\n"
            f"  name:            {MOUSE_NAME}\n"
            f"  vendor:          0x{MOUSE_VENDOR:04x}\n"
            f"  product:         0x{MOUSE_PRODUCT:04x}\n"
            f"  rel_x:           {e.REL_X}\n"
            f"  rel_y:           {e.REL_Y}\n"
            f"  rel_wheel:       {e.REL_WHEEL}\n"
            f"  btn_left:        {e.BTN_LEFT}\n"
            f"  btn_middle:      {e.BTN_MIDDLE}\n"
            f"  btn_right:       {e.BTN_RIGHT}\n"
        )

    def wheel(self, direction):
        direction = direction.lower()
        if direction == "up":
            value = 1
        elif direction == "down":
            value = -1
        else:
            raise ValueError("mouse wheel: expected up|down")

        self._rel(e.REL_WHEEL, value)
        return f"mouse: wheel {direction}\n"

    def wheel_spin_start(self, mode="start"):
        if mode not in ("start", "fast"):
            raise ValueError("expected start|fast")

        self.wheel_spin_stop()

        with self._lock:
            if self._ui is None:
                raise RuntimeError("mouse is unplugged")

            self._wheel_spin_stop.clear()
            self._wheel_spin_mode = mode
            self._wheel_spin_thread = threading.Thread(target=self._wheel_spin_loop, args=(mode,), daemon=True)
            self._wheel_spin_thread.start()

        return f"mouse: wheel spin={mode}\n"

    def wheel_spin_stop(self):
        with self._lock:
            thread = self._wheel_spin_thread
            self._wheel_spin_stop.set()

        if thread is not None:
            thread.join(timeout=1.0)

        with self._lock:
            if self._wheel_spin_thread is thread:
                self._wheel_spin_thread = None
            self._wheel_spin_mode = None

        return "mouse: wheel spin=off\n"

    def wheel_spin_status(self):
        return f"mouse: wheel spin={self._wheel_spin_state()}\n"

    def _wheel_spin_state(self):
        with self._lock:
            if self._wheel_spin_thread is not None and self._wheel_spin_thread.is_alive():
                return self._wheel_spin_mode or "on"
            return "off"

    def _wheel_spin_loop(self, mode):
        try:
            while not self._wheel_spin_stop.is_set():
                direction = random.choice((-1, 1))

                if mode == "fast":
                    run_seconds = random.uniform(0.2, 0.8)
                    interval = random.uniform(0.001, 0.02)
                else:
                    run_seconds = random.uniform(1.5, 5.0)
                    interval = random.uniform(0.04, 0.35)

                end_time = time.monotonic() + run_seconds

                while time.monotonic() < end_time and not self._wheel_spin_stop.is_set():
                    try:
                        self._rel(e.REL_WHEEL, direction)
                    except RuntimeError:
                        return
                    time.sleep(interval)
        finally:
            with self._lock:
                self._wheel_spin_thread = None
                self._wheel_spin_mode = None
                self._wheel_spin_stop.set()

    def button_down(self, button):
        self._button(button, 1)
        return f"mouse: down {button}\n"

    def button_up(self, button):
        self._button(button, 0)
        return f"mouse: up {button}\n"

    def click(self, button):
        self._key(self._button_code(button))
        return f"mouse: click {button}\n"

    def move(self, x, y):
        x = int(x)
        y = int(y)

        with self._lock:
            ui = self._ui

        if ui is None:
            raise RuntimeError("mouse is unplugged")

        ui.write(e.EV_REL, e.REL_X, x)
        ui.write(e.EV_REL, e.REL_Y, y)
        ui.syn()
        return f"mouse: move x={x} y={y}\n"

    def _button_code(self, button):
        button = button.lower()
        if button not in self.BUTTONS:
            raise ValueError("mouse button: expected left|middle|right")
        return self.BUTTONS[button]

    def _button(self, button, value):
        key = self._button_code(button)

        with self._lock:
            ui = self._ui

        if ui is None:
            raise RuntimeError("mouse is unplugged")

        ui.write(e.EV_KEY, key, int(value))
        ui.syn()

    def _key(self, key):
        with self._lock:
            ui = self._ui

        if ui is None:
            raise RuntimeError("mouse is unplugged")

        ui.write(e.EV_KEY, key, 1)
        ui.syn()
        time.sleep(self.press_time)
        ui.write(e.EV_KEY, key, 0)
        ui.syn()

    def _rel(self, code, value):
        with self._lock:
            ui = self._ui

        if ui is None:
            raise RuntimeError("mouse is unplugged")

        ui.write(e.EV_REL, code, int(value))
        ui.syn()


class ControlServer:
    def __init__(self, *, host, port, knob, mouse, stop_event):
        self.host = host
        self.port = port
        self.knob = knob
        self.mouse = mouse
        self.stop_event = stop_event

        self._stop = threading.Event()
        self._listen_sock = None
        self._thread = None

    def start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with suppress(OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

        sock.bind((self.host, self.port))
        sock.listen(5)
        sock.settimeout(0.2)

        self._listen_sock = sock
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        print(f"Input control: up on {self.host}:{self.port}", flush=True)

    def stop(self):
        self._stop.set()
        sock = self._listen_sock
        self._listen_sock = None

        if sock is not None:
            with suppress(OSError):
                sock.close()

        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self):
        while not self._stop.is_set() and not self.stop_event.is_set():
            try:
                conn, _ = self._listen_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
            thread.start()

    def _send(self, conn, text):
        conn.sendall(text.encode("utf-8"))

    def _handle_client(self, conn):
        buf = bytearray()

        with conn:
            self._send(conn, "PanSyncer testlab input control. Type 'help'.\n")
            self._send(conn, "inputlab> ")

            while not self.stop_event.is_set():
                try:
                    data = conn.recv(1024)
                except OSError:
                    return

                if not data:
                    return

                buf.extend(data)

                while b"\n" in buf:
                    raw, _, rest = buf.partition(b"\n")
                    buf = bytearray(rest)

                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        self._send(conn, "inputlab> ")
                        continue

                    try:
                        result, close_connection = self._dispatch(line)
                    except UInputError as exc:
                        result = format_uinput_error(exc, self.port)
                        close_connection = False
                    except Exception as exc:
                        result = f"error: {exc}\n"
                        close_connection = False

                    self._send(conn, result)

                    if close_connection:
                        return

                    self._send(conn, "inputlab> ")

    def _dispatch(self, line):
        parts = line.split()
        command = parts[0].lower()
        args = parts[1:]

        if command == "help":
            return self._help(), False

        if command == "status":
            return self._status(), False

        if command == "shutdown":
            self.stop_event.set()
            return "shutting down input testlab\n", True

        if command == "knob":
            return self._handle_knob(args), False

        if command == "mouse":
            return self._handle_mouse(args), False

        return "unknown command; type 'help'\n", False

    def _handle_knob(self, args):
        if not args:
            raise ValueError("missing knob action")

        action = args[0].lower()
        rest = args[1:]

        if action == "plug":
            return self.knob.plug()

        if action == "unplug":
            return self.knob.unplug()

        if action == "cycle":
            return self.knob.cycle()

        if action == "up":
            return self.knob.up()

        if action == "down":
            return self.knob.down()

        if action == "click":
            return self.knob.click()

        if action == "flood":
            if not rest:
                raise ValueError("knob flood: missing argument, expected <count> [interval_ms]")
            count = int(rest[0])
            interval_ms = int(rest[1]) if len(rest) > 1 else DEFAULT_INTERVAL_MS
            return self.knob.flood(count, interval_ms)

        if action == "spin":
            if not rest:
                raise ValueError("knob spin: missing argument, expected start|fast|stop|status")
            mode = rest[0].lower()
            if mode == "start":
                return self.knob.spin_start("start")
            if mode == "fast":
                return self.knob.spin_start("fast")
            if mode == "stop":
                return self.knob.spin_stop()
            if mode == "status":
                return self.knob.spin_status()
            raise ValueError("knob spin: expected start|fast|stop|status")

        raise ValueError(f"unknown knob action: {action}")

    def _handle_mouse(self, args):
        if not args:
            raise ValueError("missing mouse action")

        action = args[0].lower()
        rest = args[1:]

        if action == "plug":
            return self.mouse.plug()

        if action == "unplug":
            return self.mouse.unplug()

        if action == "cycle":
            return self.mouse.cycle()

        if action == "wheel":
            if not rest:
                raise ValueError("mouse wheel: missing argument, expected up|down|spin")
            sub = rest[0].lower()

            if sub in ("up", "down"):
                return self.mouse.wheel(sub)

            if sub == "spin":
                if len(rest) < 2:
                    raise ValueError("mouse wheel spin: missing argument, expected start|fast|stop|status")
                mode = rest[1].lower()
                if mode == "start":
                    return self.mouse.wheel_spin_start("start")
                if mode == "fast":
                    return self.mouse.wheel_spin_start("fast")
                if mode == "stop":
                    return self.mouse.wheel_spin_stop()
                if mode == "status":
                    return self.mouse.wheel_spin_status()
                raise ValueError("mouse wheel spin: expected start|fast|stop|status")

            raise ValueError("mouse wheel: expected up|down|spin")

        if action in ("up", "down", "click"):
            if not rest:
                raise ValueError(f"mouse {action}: missing argument, expected left|middle|right")
            button = rest[0].lower()
            if action == "up":
                return self.mouse.button_up(button)
            if action == "down":
                return self.mouse.button_down(button)
            return self.mouse.click(button)

        if action == "move":
            if len(rest) < 2:
                raise ValueError("mouse move: missing arguments, expected <pixel_x> <pixel_y>")
            return self.mouse.move(rest[0], rest[1])

        raise ValueError(f"unknown mouse action: {action}")

    def _status(self):
        return self.knob.status() + "\n" + self.mouse.status()

    def _help(self):
        return """Commands:
  help
  status
  shutdown

  knob plug
  knob unplug
  knob cycle
  knob up
  knob down
  knob click
  knob flood <count> [interval_ms]
  knob spin start|fast|stop|status

  mouse plug
  mouse unplug
  mouse cycle
  mouse wheel up|down
  mouse wheel spin start|fast|stop|status
  mouse up left|middle|right
  mouse down left|middle|right
  mouse click left|middle|right
  mouse move <pixel_x> <pixel_y>
"""


def parse_args():
    parser = argparse.ArgumentParser(description="PanSyncer manual test fake input lab")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--no-auto-plug", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    stop_event = threading.Event()
    knob = FakeKnob()
    mouse = FakeMouse()
    control = ControlServer(
        host=args.host,
        port=args.control_port,
        knob=knob,
        mouse=mouse,
        stop_event=stop_event,
    )

    try:
        if os.geteuid() != 0:
            print("warning: this usually needs write access to /dev/uinput", file=sys.stderr)

        if not args.no_auto_plug:
            try:
                print(knob.plug(), end="")
                print(mouse.plug(), end="")
            except UInputError as exc:
                print(format_uinput_error(exc, args.control_port), end="", file=sys.stderr)
                return 1

        control.start()

        print()
        print("Control:")
        print(f"  rlwrap nc {args.host} {args.control_port}")
        print()
        print("Press Ctrl-C here or use 'shutdown' on the control socket.")

        while not stop_event.is_set():
            time.sleep(0.2)

    except KeyboardInterrupt:
        pass
    finally:
        control.stop()

        if knob._ui is not None:
            print(knob.unplug(), end="")

        if mouse._ui is not None:
            print(mouse.unplug(), end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())