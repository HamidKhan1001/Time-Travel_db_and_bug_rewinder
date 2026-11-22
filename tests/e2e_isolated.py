"""Run the demo E2E script against an isolated temporary copy of project runtime files."""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    with tempfile.TemporaryDirectory(prefix="tt-e2e-") as tmp:
        for directory in ("app", "seed", "timetravel", "tests", "data"):
            source = os.path.join(ROOT, directory)
            destination = os.path.join(tmp, directory)
            shutil.copytree(source, destination)

        shutil.copy2(os.path.join(ROOT, "reset.py"), os.path.join(tmp, "reset.py"))
        env = os.environ.copy()
        env["TT_PACE"] = "0"

        completed = subprocess.run(
            [sys.executable, "tests/e2e.py"],
            cwd=tmp,
            env=env,
            check=False,
        )
        if completed.returncode:
            raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
