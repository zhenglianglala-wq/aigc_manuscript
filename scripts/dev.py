"""Start both local services and terminate both when interrupted."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=5173)
    args = parser.parse_args()
    node = shutil.which("node") or str(BUNDLE / "node/bin/node")
    pnpm = shutil.which("pnpm")
    if pnpm:
        command = [pnpm]
    else:
        bundled = BUNDLE / "node/node_modules/pnpm/bin/pnpm.cjs"
        if not Path(node).exists() or not bundled.exists():
            raise SystemExit("Install Node.js and pnpm, then run scripts/setup.sh.")
        command = [node, str(bundled)]
    env = os.environ.copy()
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    env["API_TARGET"] = f"http://127.0.0.1:{args.api_port}"
    env["VITE_API_TARGET"] = env["API_TARGET"]
    commands = [
        ([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
          "--port", str(args.api_port)], ROOT),
        (command + ["dev", "--host", "127.0.0.1", "--port", str(args.web_port)], ROOT / "frontend"),
    ]
    children = []

    def stop(*_: object) -> None:
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command, cwd in commands:
            children.append(subprocess.Popen(command, cwd=cwd, env=env))
        print(f"Web: http://127.0.0.1:{args.web_port} | API: http://127.0.0.1:{args.api_port}", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.3)
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
