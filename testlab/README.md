# PanSyncer Testlab

Manual test environment for PanSyncer without real hardware.

It provides:

- fake rigctld TCP endpoint
- fake Gqrx TCP endpoint
- fake VFO knob via Linux `uinput`
- fake mouse via Linux `uinput`
- simple control consoles via `nc`; use `rlwrap nc` for command history and editing

## Table of Contents

- [Fake Radios](#fake-radios)
  - [Start Fake Radios](#start-fake-radios)
  - [Radio General Commands](#radio-general-commands)
  - [Rig and Gqrx Commands](#rig-and-gqrx-commands)
  - [CAT Watch](#cat-watch)
- [Fake Inputs](#fake-inputs)
  - [Start Fake Inputs](#start-fake-inputs)
  - [Optional udev Setup](#optional-udev-setup)
  - [Input General Commands](#input-general-commands)
  - [Knob Commands](#knob-commands)
  - [Mouse Commands](#mouse-commands)
- [Typical Test Setup](#typical-test-setup)

## Fake Radios

### Start Fake Radios

```bash
python testlab/fake_radios.py --rig-port 4533 --gqrx-port 7357 --control-port 4534
```

Control console:

```bash
rlwrap nc 127.0.0.1 4534
```

Start PanSyncer:

```bash
python -m pansyncer.main --rig-port 4533 --gqrx-port 7357 --no-auto-rig
```

iFreq mode:

```bash
python testlab/fake_radios.py --rig-port 4533 --gqrx-port 7357 --control-port 4534 --ifreq 73.095
python -m pansyncer.main --rig-port 4533 --gqrx-port 7357 --no-auto-rig --ifreq 73.095
```

### Radio General Commands

```text
help                  show commands
status                show current fake radio state
shutdown              stop fake_radios.py
```

### Rig and Gqrx Commands

```text
rig up                start fake Rig TCP server
rig down              stop fake Rig TCP server
rig restart           restart fake Rig TCP server
rig freq <hz>         set Rig frequency
rig nudge [hz]        change Rig frequency, default +100 Hz; accepts negative values
rig delay <seconds>   delay CAT replies
rig mode valid        normal replies
rig mode invalid      reply with invalid frequency text
rig mode silent       keep socket open but send no replies
rig mode rprt-error   reply with RPRT -1
rig spin start        vary Rig frequency
rig spin fast         vary Rig frequency fast
rig spin stop         stop Rig spin
rig spin status       show Rig spin status

gqrx                  has the full Rig command set, plus:
gqrx lo <hz>          set fake Gqrx LNB_LO
```

### CAT Watch

Open a second control console:

```bash
rlwrap nc 127.0.0.1 4534
```

Watch CAT traffic:

```text
watch all
watch rig
watch gqrx
```

Leave watch mode:

```text
q
```

## Fake Inputs

Manual test environment for PanSyncer input devices without physical knob or mouse.

`fake_inputs.py` creates Linux `uinput` devices:

```text
Fake VFO Knob
Fake Mouse
Control socket: 4537
```

### Start Fake Inputs

Load `uinput` if needed:

```bash
sudo modprobe uinput
```

Start with the project venv:

```bash
sudo .venv/bin/python testlab/fake_inputs.py --control-port 4537
```

Control console:

```bash
rlwrap nc 127.0.0.1 4537
```

Start PanSyncer with fake inputs:

```bash
python -m pansyncer.main -d r g k m --rig-port 4533 --gqrx-port 7357 --no-auto-rig
```

### Optional udev Setup

Allow non-root access to `/dev/uinput`:

```bash
sudo usermod -aG input "$USER"
echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/99-uinput.rules
echo uinput | sudo tee /etc/modules-load.d/uinput.conf
sudo modprobe uinput
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Log out and back in. Then start without `sudo`:

```bash
.venv/bin/python testlab/fake_inputs.py --control-port 4537
```

### Input General Commands

```text
help                  show commands
status                show fake input state
shutdown              stop fake_inputs.py
```

### Knob Commands

```text
knob plug             create fake knob device
knob unplug           remove fake knob device
knob cycle            unplug and plug fake knob
knob up               send one VFO-up event
knob down             send one VFO-down event
knob click            send knob-click event
knob flood <n> [ms]   send many knob events; negative n means down
knob spin start       random slow knob turns
knob spin fast        random fast knob turns
knob spin stop        stop knob spin
knob spin status      show knob spin status
```

### Mouse Commands

```text
mouse plug            create fake mouse device
mouse unplug          remove fake mouse device
mouse cycle           unplug and plug fake mouse
mouse wheel up        send one wheel-up event
mouse wheel down      send one wheel-down event
mouse wheel spin start
mouse wheel spin fast
mouse wheel spin stop
mouse wheel spin status
mouse up left|middle|right
mouse down left|middle|right
mouse click left|middle|right
mouse move <x> <y>    move mouse by relative pixels
```

## Typical Test Setup

Terminal 1: fake radios

```bash
python testlab/fake_radios.py --rig-port 4533 --gqrx-port 7357 --control-port 4534
```

Terminal 2: fake inputs

```bash
sudo .venv/bin/python testlab/fake_inputs.py --control-port 4537
```

Terminal 3: PanSyncer

```bash
python -m pansyncer.main -d r g k m --rig-port 4533 --gqrx-port 7357 --no-auto-rig
```

Terminal 4: radio control

```bash
rlwrap nc 127.0.0.1 4534
```

Terminal 5: CAT watch

```bash
rlwrap nc 127.0.0.1 4534
watch all
```

Terminal 6: input control

```bash
rlwrap nc 127.0.0.1 4537
```

iFreq variant:

```bash
python testlab/fake_radios.py --rig-port 4533 --gqrx-port 7357 --control-port 4534 --ifreq 73.095
python -m pansyncer.main -d r g k m --rig-port 4533 --gqrx-port 7357 --no-auto-rig --ifreq 73.095
```