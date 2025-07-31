# PanSyncer

PanSyncer is designed to synchronize the frequencies of a ham radio transceiver and an SDR receiver using GQRX.
External input devices like a USB Volume Knob, mouse or keyboard can be used to tune the frequency.

## Table of Contents  

* [Motivation](#motivation)
* [Architecture](#architecture)
* [Installation and configuration](#installation-and-configuration)
  * [Environment](#environment)
  * [Installation](#installation)
  * [Config file and command line arguments](#config-file-and-command-line-arguments)
* [Usage](#usage)
  * [User Interface](#user-interface)
  * [Daemon mode](#daemon-mode)
  * [rigctld handling](#rigctld-handling)
  * [Frequency logging](#frequency-logging)
  * [Synchronization Modes](#synchronization-modes)
    * [Direct Mode](#direct-mode)
    * [Standalone Mode](#standalone-mode)
    * [iFreq Mode](#ifreq-mode)
      * [Initial Synchronization for GQRX in iFreq mode](#initial-synchronization-for-gqrx-in-ifreq-mode)
* [Use a USB Volume Knob as VFO Knob](#use-a-usb-volume-knob-as-vfo-knob)  
  * [Identify device](#identify-device)
  * [Find event node](#find-event-node)
  * [Inspect events and key mappings](#inspect-events-and-key-mappings)
  * [Give user permission to use knob device](#give-user-permission-to-use-knob-device)
  * [Configure PanSyncer to use the Knob Device](#configure-pansyncer-to-use-the-knob-device)

## Motivation

My portable ham station uses a QMX+ transceiver and Airspy HF+ SDR, coupled using an antenna splitter. 
That setup also includes a Raspberry Pi as the controller. Although everything is digital now:
I wanted an external VFO knob for the classic analog‑dial feel.
I also wanted to use a reasonably priced "USB External Volume Control Knob" for that purpose.
And I needed a solution to synchronize the Rig to the SDR. Having used the great
[gqrx-panadapter](https://github.com/alexf91/gqrx-panadapter) script for years to couple my iFreq-tapped
Kenwood TS-480, I wished for more features, like Direct Mode auto-reconnect on errors.

So I combined these requirements into one program. Here it is!


## Architecture

A typical setup might look as follows:
```
                                             +-------------------+
                        #############        | Input devices     |
          +-----------> # PanSyncer # <----- | Keyboard, Mouse,  |
          |             #############        | External VFO Knob | 
          |                   ^              +-------------------+
          |                   |
          v                   v 
    +-----------+       +-----------+        +-----------+        +-----------+            
    |   GQRX    |       |  rigctld  | <----> |   FLRig   | <----> | TRX (Rig) |
    +-----------+       +-----------+        +-----------+        +-----------+
                              ^                    ^
                              |                    |
                              v                    v
                        +-----------+        +-----------+                           
                        |  Logger   |        |  WSJT-X   |
                        +-----------+        +-----------+
```

The use of FLRig, Logger or Digi-Client (e.g. WSJT-X) is optional. PanSyncer can also connect to two rigctld instances,
running on different ports (specified as rig_port and gqrx_port) which may then connect to two ham radios or any other
hamlib client. This will only work in Direct Mode and you must start rigctld manually.

[TOC](#table-of-contents)
## Installation and configuration

### Environment

* PanSyncer runs on  *Linux*. It is using system-specific dependencies like evdev and select.
There are no plans to port PanSyncer to Windows.
* *Python* >= 3.8 - which should be included in any recent Linux distribution. The dependencies are installed
as described below. 
* PanSyncer is meant to be run from an VT100‑compatible ANSI terminal, unless you use it as a background process.
Most Linux terminals support this.
* *[hamlib](https://hamlib.github.io/) rigctl* is essential - unless you are planning to use GQRX standalone only.
Most linux distribution have a hamlib package. Installing that is the best choice in most cases. On Debian/Ubuntu
the command to install is:  
`sudo apt-get install libhamlib-utils`  
On other distros, the package is usually named `hamlib`.

### Installation

* To install:
  * Clone the repo 
  * Enter its folder  
  * Install to ~/.local/bin (make sure that's in your PATH)  

      ```
      git clone https://github.com/makrohard/pansyncer.git
      cd pansyncer
      pip install --user .
      ```  
  * Run
      ```
      pansyncer --help
      ```

      Uninstall with: `pip uninstall pansyncer`
  

* Alternatively you can run the script without installation:
  * Clone the repo
  * Enter its folder
  * Create python virtual environment
  * Activate virtual environment
  * Install requirements
  * Run PanSyncer as module

      ```
      git clone https://github.com/makrohard/pansyncer.git
      cd pansyncer
      python -m venv .venv
      source .venv/bin/activate
      pip install -r requirements.txt
      python -m pansyncer.main --help
      ```
  * Just remember, that you will have to activate the venv manually in each shell, before starting PanSyncer:
      ```
      source .venv/bin/activate
      python -m pansyncer.main --help
      ```

### Config file and command line arguments

By default, PanSyncer uses Direct Mode and connects rigctld to FLRig. To configure PanSyncer to match
your environment, you have two options:

* Use command line arguments. `pansyncer --help` will show you the usage
* Use the config file: `pansyncer.toml`

Command line arguments will overwrite the config file.

[TOC](#table-of-contents)
## Usage

### User Interface

PanSyncer provides a terminal based user interface.

The upper‑right shows the active mode, which can’t be changed at runtime.  
The left column lists active devices; the next column shows their connection status. Active devices will be monitored
and try to reconnect. Devices can be toggled at runtime.  
In the right column, for radios the current frequency is shown. For input devices, a short flash for the input is shown. 
Log messages are shown below the last device. Logging parameters can be specified in `pansyncer.toml`.

Note:  
Keyboard cannot be disabled. It uses stdin and does not need any connection logic.  
Rig has two connection statuses: Gray means "rigctld socket alive"; Green means "Getting frequency response from rig".

```
 PanSyncer Control      iFreq
 Sync      ON   73.095.000 Hz
 Step                  100 Hz
 Rig       CON  14.172.100 Hz
 Gqrx      CON  14.172.000 Hz
 Knob      CON     
 Mouse     CON     
 Keyboard       UP 
```

Pressing **?** shows help:

```
[INFO] Change Frequency :  + / -, arrow keys, mouse or external VFO Knob
[INFO] Sync On / Off    :  1 / 0
[INFO] Change Step      :  Spacebar, middle mouse button or knob click
[INFO] Toggle devices   :  r = Rig,  g = Gqrx, m = Mouse k = VFO Knob
[INFO] Quit             :  q 
```


### Daemon mode

PanSyncer can also be run in the background, using the `-b` or `--daemon` flag. This will disable display and keyboard.
You can use `Ctrl C` to shutdown PanSyncer. Press once, and wait patiently. 

To send PanSyncer fully to the background, you can add an `&` at the end of your command. Use this command, to launch 
Pansyncer into the background and suppress all output:

`pansyncer -b >/dev/null 2>&1 &`

Be careful not to launch multiple instances, as they will block ports and grab devices.

To list running instances:    
```
ps ax | grep pansyncer  
24258 pts/0    Sl+    0:00 python -m pansyncer.main -b  
```
Kill the process by its PID:
`kill 24258`  

### rigctld handling

By default, PanSyncer starts rigctld as a subprocess. It restarts on crashes and terminates at shutdown.

If you prefer to start rigctld manually, use the `--no-auto-rig` argument, or set it in the config file. 

The rigctld command can be configured in the `pansyncer.toml` config file. You may want to do that.
Default configuration is to use FLRig xmlrpc.

### Frequency logging

The frequency logger writes a line with a timestamp and the rig’s frequency to a file whenever the frequency changes.
It briefly waits before doing so to avoid flooding the file. It can serve as a backup for the regular logging program
if that program occasionally loses the CAT connection without being noticed. The frequency logger is disabled by default
and can be enabled by specifying a filename.

Do not confuse it with the program loggers, which can also write to a file for debugging purposes.

### Synchronization Modes

#### Direct Mode

**This mode is enabled by default, if the `--ifreq` flag is not set.**  
The Direct Mode synchronizes two radios to the same frequency. This is suitable, if you have independent antennas for
your radios or if the antenna signal is split and used for both radios. This mode synchronizes the frequencies
bidirectional, allowing both radios to be directly tuned while staying synchronized.


#### Standalone Mode
**Activating only one radio or deactivating sync will use that mode.**  
Synchronization may be switched off, as well as one of the two radios. The input devices will still work. That way it is
possible to use PanSyncer to couple your external VFO Knob to your radio - or just use mouse or keyboard to change the
frequency. If Rig is present, it will always have priority (even when disconnected).

#### iFreq Mode

**Activate this mode by setting the ifreq flag e.g. `--ifreq 73.095`**  
The Intermediate Frequency Mode is designed for the use with the IF-Out (or buffered iFreq-tap) on a classic
Transceiver (Superhet). This mode will "scroll the background" by changing the LO_LNB (Hardware freq) of GQRX to
match the hardware-coupled frequency-scrolling of your rig.

You will be able to use the offset frequency by clicking in the waterfall and listen to neighbour signals. You may also
use the offset frequency to match the signal and the GQRX indicator, if it is off by a bit. You can reset the
offset any time by right-clicking the highest digit in the `Receiver Options` window.

Changing the GQRX main frequency however, will throw you out of sync. If that happens, just turn the GQRX main
frequency to the RIG frequency again. When in sync, "Hardware freq" will always match the iFreq.

In iFreq Mode, RIG will sync to GQRX, but not the other way round.

##### Initial Synchronization for GQRX in iFreq mode

In order to synchronize GQRX initially in iFreq Mode, you will have to set the Local Oscillator Frequency
(Hardware freq) to match the Intermediate Frequency of your Transceiver. This can be done as follows:

* `View -> Receiver Options` 
* `Receiver Options` -> Set offset to 0 (right-click the highest digit)
* `File -> I/O Devices: I/Q input: LO_LNB` -> Enter 0 and click OK
* `Frequency` -> Set to 0
* Check: All frequencies zeroed
* Start PanSyncer in iFreq Mode: Use `--ifreq 73.095` with the intermediate frequency of your TRX. That will set
the LO Frequency in GQRX accordingly
* `Frequency` -> Set to RIG frequency manually
* Check `Receiver Options: Hardware freq` => This should now match the GQRX and RIG frequency
* You are now in sync.

It might be possible in future developments to synchronize the iFreq automatically, as well as making iFreq Mode
bidirectional, when [IF tap sync support](https://github.com/gqrx-sdr/gqrx/pull/1422) will be added to GQRX.
For now, you will have to perform that steps manually.

[TOC](#table-of-contents)
## Use a USB Volume Knob as VFO Knob

External VFO knobs do exist, but they are often made for a specific radio, are very expensive, or require soldering and hardware‑level programming.
However, there are many affordable USB volume knobs on the market that provide exactly the hardware we need.

PanSyncer already supports several knobs. If you are lucky, your knob will work out of the box.
If not, it may be a permission issue, or you may need to configure it manually. Here is how to set it up:

### Identify device

Run:
`sudo dmesg -w`  
Then plug in the USB knob. Look for lines that show idVendor and idProduct.  
In this example: idVendor=05ac, idProduct=0202 

```
[27531.159576] usb 1-2: new full-speed USB device number 17 using xhci_hcd
[27531.284796] usb 1-2: New USB device found, idVendor=05ac, idProduct=0202, bcdDevice= 1.04
[27531.284805] usb 1-2: New USB device strings: Mfr=0, Product=1, SerialNumber=0
[27531.284809] usb 1-2: Product: Wired KeyBoard
[27531.288949] input: Wired KeyBoard as /devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0/0003:05AC:0202.000B/input/input24
[27531.365788] hid-generic 0003:05AC:0202.000B: input,hidraw0: USB HID v1.10 Keyboard [Wired KeyBoard] on usb-0000:00:14.0-2/input0
[27531.368348] input: Wired KeyBoard System Control as /devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.1/0003:05AC:0202.000C/input/input25
[27531.418945] input: Wired KeyBoard Consumer Control as /devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.1/0003:05AC:0202.000C/input/input26
[27531.419043] input: Wired KeyBoard Mouse as /devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.1/0003:05AC:0202.000C/input/input27
[27531.419210] hid-generic 0003:05AC:0202.000C: input,hidraw1: USB HID v1.10 Mouse [Wired KeyBoard] on usb-0000:00:14.0-2/input1
```

### Find event node
A Knob may present multiple devices (Keyboard, System Control, Consumer Control, Mouse),
which even may all have the same name. We must find the correct one.

Replace *Consumer Control* with your device name and run:
```
grep -B1 -A5 "Consumer Control" /proc/bus/input/devices
```
Example output:

```
I: Bus=0003 Vendor=05ac Product=0202 Version=0110
N: Name="Wired KeyBoard Consumer Control"
P: Phys=usb-0000:00:14.0-2/input1
S: Sysfs=/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.1/0003:05AC:0202.000C/input/input26
U: Uniq=
H: Handlers=kbd event5 
B: PROP=0
```
The line starting with `H:` shows the event node.

### Inspect events and key mappings

Using that event node, run:

```
sudo evtest /dev/input/event5
```

Turn and click the knob. If you see no output, try a different event node.  
Note that we are using sudo to run the command as root. If `evtest` works on the correct event node as a normal user,
you do not need to change any permissions, which are explained later.

Example output:

```
Testing ... (interrupt to exit)
Event: time 1753651144.743483, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00e9
Event: time 1753651144.743483, type 1 (EV_KEY), code 115 (KEY_VOLUMEUP), value 1
Event: time 1753651144.743483, -------------- SYN_REPORT ------------
Event: time 1753651144.745455, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00e9
Event: time 1753651144.745455, type 1 (EV_KEY), code 115 (KEY_VOLUMEUP), value 0
Event: time 1753651144.745455, -------------- SYN_REPORT ------------
Event: time 1753651151.233693, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00ea
Event: time 1753651151.233693, type 1 (EV_KEY), code 114 (KEY_VOLUMEDOWN), value 1
Event: time 1753651151.233693, -------------- SYN_REPORT ------------
Event: time 1753651151.235667, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00ea
Event: time 1753651151.235667, type 1 (EV_KEY), code 114 (KEY_VOLUMEDOWN), value 0
Event: time 1753651151.235667, -------------- SYN_REPORT ------------
Event: time 1753651156.411861, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00e2
Event: time 1753651156.411861, type 1 (EV_KEY), code 113 (KEY_MUTE), value 1
Event: time 1753651156.411861, -------------- SYN_REPORT ------------
Event: time 1753651156.414845, type 4 (EV_MSC), code 4 (MSC_SCAN), value c00e2
Event: time 1753651156.414845, type 1 (EV_KEY), code 113 (KEY_MUTE), value 0
Event: time 1753651156.414845, -------------- SYN_REPORT ------------
```

If you see the events: Congratulations, you found your device. This output shows the key-mappings, that
we will use later.

### Give user permission to use knob device

By default, users often cannot access input devices. Add your user to the input group:

```
sudo usermod -aG input $USER
```
Log out and back in to apply the change.

Next, create a udev rule to automatically set the correct permissions.

Create a new file:

`/etc/udev/rules.d/99-vfo-knob.rules`

And put the new rule there. The example below contains all knobs currently known to PanSyncer.  
Make sure, that use your Device Name, ifVendor and idProduct.

```
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{name}=="Wired KeyBoard Consumer Control", ATTRS{idVendor}=="05ac", ATTRS{idProduct}=="0202", GROUP="input", MODE="0660"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{name}=="LCTECH LCKEY", ATTRS{idVendor}=="1189", ATTRS{idProduct}=="8890", GROUP="input", MODE="0660"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{name}=="413d:553a", ATTRS{idVendor}=="413d", ATTRS{idProduct}=="553a", GROUP="input", MODE="0660"

```
Reload the udev rules to apply the changes:
```
sudo udevadm control --reload-rules
sudo udevadm trigger
```
You should now be able to use your knob as user.

### Configure PanSyncer to use the knob device

To make your knob known to PanSyncer, add a new `[[knobs]]` section  `pansyncer.toml` config file.
Make sure to prefix target_vendor and target_product with 0x and to copy the target_name exactly.

```
[[knobs]]                                               ### Configure Knobs
target_name    = "Wired KeyBoard Consumer Control"      # Device Identification
target_vendor              = 0x05ac                     # Prefix 0x for hex value
target_product             = 0x0202
                                                        # Key mappings
key_up                     = 115                        # ecodes.KEY_VOLUMEUP
key_down                   = 114                        # ecodes.KEY_VOLUMEDOWN
key_step                   = 113                        # ecodes.KEY_MUTE
```

With that in place, PanSyncer should now find and connect your knob.

If at this point everything is looking good, but the knob is not working as expected: A reboot might help as it will
apply the group settings of the user and the udev-rule.  

If you have successfully integrated a new knob, please consider opening an issue on
[GitHub](https://github.com/makrohard/pansyncer/issues), or write me an eMail to 
[410733\@gmail.com](mailto:410744\@gmail.com) with idVendor, idProduct and name.
I will gladly add support for more knobs by default.
