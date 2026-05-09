#!/usr/bin/env bash
set -euo pipefail

SESSION="pansyncer-demo"
RUN_DIR="/tmp/pansyncer-demo"

cd "$(git rev-parse --show-toplevel)"
export REPO_DIR="$PWD"

mkdir -p "$RUN_DIR"

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

source .venv/bin/activate

if ! python -m pip show pansyncer >/dev/null 2>&1; then
  python -m pip install -e .
fi

cat > "$RUN_DIR/common.sh" <<EOF
#!/usr/bin/env bash

REPO_DIR=$(printf '%q' "$REPO_DIR")

cd_repo() {
  cd "\$REPO_DIR"
}

wait_port() {
  local port="\$1"

  for _ in \$(seq 1 50); do
    if nc -z 127.0.0.1 "\$port" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done

  echo "timeout waiting for port \$port" >&2
  return 1
}
EOF

cat > "$RUN_DIR/server.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

source /tmp/pansyncer-demo/common.sh
cd_repo
source .venv/bin/activate

python testlab/fake_radios.py --rig-port 4533 --gqrx-port 7357 --control-port 4534
exec bash
EOF

cat > "$RUN_DIR/pansyncer.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

source /tmp/pansyncer-demo/common.sh
cd_repo
source .venv/bin/activate

wait_port 4533
wait_port 7357

python -m pansyncer.main -d r g m --rig-port 4533 --gqrx-port 7357 --no-auto-rig
exec bash
EOF

cat > "$RUN_DIR/control.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

source /tmp/pansyncer-demo/common.sh
cd_repo

wait_port 4534

echo "tmux window control"
echo "  Ctrl-b + Arrow     switch pane"
echo "  Ctrl-b + [         scroll mode"
echo "  q                  leave scroll mode"
echo ""
echo "RADIO EMULATOR CONTROL"
echo "Example commands:"
echo "  status"
echo "  rig nudge -100"
echo "  gqrx spin start"
echo ""

rlwrap nc 127.0.0.1 4534
exec bash
EOF

cat > "$RUN_DIR/watch_rig.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

source /tmp/pansyncer-demo/common.sh
cd_repo

wait_port 4534

echo "WATCH RIG"

rlwrap nc 127.0.0.1 4534
exec bash
EOF

cat > "$RUN_DIR/watch_gqrx.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

source /tmp/pansyncer-demo/common.sh
cd_repo

wait_port 4534

echo "WATCH GQRX"

rlwrap nc 127.0.0.1 4534
exec bash
EOF

chmod +x "$RUN_DIR/"*.sh

tmux kill-session -t "$SESSION" 2>/dev/null || true

tmux new-session -d -s "$SESSION" -n _server "$RUN_DIR/server.sh"

tmux new-window -t "$SESSION" -n demo "$RUN_DIR/pansyncer.sh"

PANE_PANSYNCER="$(tmux display-message -p -t "$SESSION:demo.0" "#{pane_id}")"

PANE_CONTROL="$(tmux split-window -h -P -F "#{pane_id}" -t "$PANE_PANSYNCER" "$RUN_DIR/control.sh")"
PANE_WATCH_RIG="$(tmux split-window -v -P -F "#{pane_id}" -t "$PANE_CONTROL" "$RUN_DIR/watch_rig.sh")"
PANE_WATCH_GQRX="$(tmux split-window -v -P -F "#{pane_id}" -t "$PANE_WATCH_RIG" "$RUN_DIR/watch_gqrx.sh")"

tmux select-layout -t "$SESSION:demo" tiled

sleep 0.5
tmux send-keys -t "$PANE_WATCH_RIG" "watch rig" C-m
tmux send-keys -t "$PANE_WATCH_GQRX" "watch gqrx" C-m

tmux select-window -t "$SESSION:demo"
tmux select-pane -t "$PANE_PANSYNCER"
tmux attach -t "$SESSION"