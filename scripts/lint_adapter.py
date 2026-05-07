import sys
import glob

FORBIDDEN_KEYWORDS = [
    "except SelectorFailedError",
    "except PageTimeoutError",
    "await self.act(",
    "await self.extract(",
    "session.current_state =",
    "time.sleep(",
    "asyncio.sleep(",
    "for _ in range(",
    "while True",
    "while attempt",
]


def check_handler(filepath):
    with open(filepath, encoding="utf-8") as f:
        source = f.read()
    failed = False
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in source:
            print(f"FAIL [{filepath}]: 包含禁止模式 '{keyword}'")
            failed = True
    if not failed:
        print(f"PASS: {filepath}")
    return failed


if __name__ == "__main__":
    any_failed = False
    for f in glob.glob("adapters/*/handler.py"):
        any_failed |= check_handler(f)
    sys.exit(1 if any_failed else 0)
