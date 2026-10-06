import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="LogWatch: live Linux log anomaly monitor")
    parser.add_argument("--demo", action="store_true", help="Start with safe synthetic log events")
    args = parser.parse_args()
    try:
        from .gui import run_gui
    except ImportError as exc:
        print(f"GUI dependencies unavailable: {exc}. Install with: python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    return run_gui(demo=args.demo)


if __name__ == "__main__":
    raise SystemExit(main())
