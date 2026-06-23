"""
pagamo_breaker — entry point

Usage:
  python main.py --hex-x -5121 --hex-y -1450 --target 3389027
  python main.py  # uses defaults from .env

Set credentials in .env (copy from .env.example).
"""
import argparse
import os
from dotenv import load_dotenv

from pagamo.auth import login
from pagamo.map_battle import run_battle

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Pagamo map battle bot")
    parser.add_argument("--hex-x", type=int, default=int(os.getenv("HEX_X", "-5121")))
    parser.add_argument("--hex-y", type=int, default=int(os.getenv("HEX_Y", "-1450")))
    parser.add_argument("--target", type=int, default=int(os.getenv("TARGET_GC_ID", "3389027")))
    parser.add_argument("--type", dest="battle_type", default="attack",
                        choices=["attack", "train"])
    parser.add_argument("--repeat", type=int, default=1,
                        help="Number of battles to run")
    args = parser.parse_args()

    account = os.getenv("PAGAMO_ACCOUNT", "")
    password = os.getenv("PAGAMO_PASSWORD", "")
    if not account or not password:
        raise SystemExit("Set PAGAMO_ACCOUNT and PAGAMO_PASSWORD in .env")

    session = login(account, password)

    wins = 0
    for i in range(args.repeat):
        if args.repeat > 1:
            print(f"\n=== Battle {i+1}/{args.repeat} ===")
        won = run_battle(
            session,
            hex_x=args.hex_x,
            hex_y=args.hex_y,
            target_gc_decoded_id=args.target,
            battle_type=args.battle_type,
        )
        if won:
            wins += 1

    if args.repeat > 1:
        print(f"\n=== Final: {wins}/{args.repeat} wins ===")


if __name__ == "__main__":
    main()
