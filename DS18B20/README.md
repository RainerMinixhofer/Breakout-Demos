# DS18B20 multi-sensor monitor

`ds18b20.py` reads one or more DS18B20/DS18S20 sensors from Linux 1-Wire sysfs and provides:
- CLI temperature output
- CLI diagnostics JSON
- Flask web dashboard with live cards, history, and per-sensor alarm/resolution settings

## 1) System prerequisites (Raspberry Pi)

Enable 1-Wire (GPIO4) and reboot.

Install owserver backend (required for writing alarm/resolution settings):

```bash
sudo apt update
sudo apt install -y owserver ow-shell
sudo systemctl enable --now owserver
```

Verify owserver is running:

```bash
systemctl is-active owserver
ss -lntp | grep 4304
```

Important: Debian's default `/etc/owfs.conf` often uses simulated devices:

```conf
server: FAKE = DS18S20,DS2405
```

Replace that line with the Linux kernel 1-Wire bus source:

```conf
server: w1
```

Then restart owserver:

```bash
sudo systemctl restart owserver
owdir -s localhost:4304 /
```

You should see your real sensors (for DS18B20: family `28.*`), not only fake `10.*` / `05.*` devices.

## 2) Python environment

From the project directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 3) Backend configuration

`ds18b20.py` writes settings through owserver using:
- default: `owserver://localhost:4304`
- optional override via `DS18B20_RAW_WRITE_BACKEND`

Example override:

```bash
export DS18B20_RAW_WRITE_BACKEND=owserver://localhost:4304
```

Only `owserver://host:port` format is supported.

## 4) Usage

### CLI temperature

```bash
. .venv/bin/activate
python ds18b20.py
```

### CLI diagnostics JSON

```bash
. .venv/bin/activate
python ds18b20.py --diagnostics
```

### Web dashboard

```bash
. .venv/bin/activate
python ds18b20.py --web --host 0.0.0.0 --port 5000
```

Open `http://<pi-ip>:5000`.

## 5) Notes on writing settings

- Alarm low/high and resolution writes are attempted through owserver (`pyownet`).
- Resolution changes are supported for DS18B20 family `28` only.
- DS18S20 (`10`) devices do not support configurable resolution.
- If sensor IDs visible via sysfs and owserver do not match, writes are rejected with a clear error message listing owserver-visible IDs.
