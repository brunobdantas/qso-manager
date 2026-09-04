#!/usr/bin/env python3
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "acceptance"
MANIFEST = ACCEPTANCE / "MANIFEST.sha256"


def verify_manifest() -> bool:
    if not MANIFEST.is_file():
        print("[LOCK FAIL] acceptance/MANIFEST.sha256 is missing")
        return False
    failures = []
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        expected, rel = raw.split(maxsplit=1)
        rel = rel.lstrip("*")
        path = ROOT / rel
        if not path.is_file():
            failures.append(f"missing: {rel}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            failures.append(f"modified: {rel}")
    if failures:
        print("[LOCK FAIL] Immutable acceptance files changed:")
        for failure in failures:
            print(" -", failure)
        return False
    print("[PASS] acceptance manifest unchanged")
    return True


def main() -> int:
    print("=" * 72)
    print("PU2BRU QSO MANAGER — EXTERNAL RELEASE 1 ACCEPTANCE")
    print("=" * 72)

    if not verify_manifest():
        print("\nRESULT: FAIL")
        print("EXIT CODE: 2")
        return 2

    with tempfile.TemporaryDirectory(prefix="pu2bru-acceptance-") as tempdir:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "backend") + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["DATABASE_URL"] = f"sqlite:///{Path(tempdir) / 'global-test.sqlite'}"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "backend/tests",
            "acceptance/tests",
            "-v",
            "-p",
            "no:cacheprovider",
            "--tb=short",
        ]
        print("COMMAND:", " ".join(cmd))
        result = subprocess.run(cmd, cwd=ROOT, env=env)

    print("\n" + "=" * 72)
    if result.returncode == 0:
        print("RESULT: PASS")
        print("EXIT CODE: 0")
        return 0
    print("RESULT: FAIL")
    print(f"EXIT CODE: {result.returncode}")
    return result.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
