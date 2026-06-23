"""
pagamo_breaker — entry point

Usage:
  python main.py --hex-x -5121 --hex-y -1450              # attack from this hex, auto-scan for enemy
  python main.py --hex-x -5121 --hex-y -1450 --type train # train on own hex
  python main.py --repeat 10                               # run 10 battles

Set credentials in .env (copy from .env.example).
MY_GC_ID is your own game character ID (from DevTools network tab).
"""
import argparse
import os
from dotenv import load_dotenv

from pagamo.auth import login
from pagamo.map_battle import run_battle

load_dotenv()

_DEFAULT_GC_ID = os.getenv("MY_GC_ID") or os.getenv("TARGET_GC_ID", "0")


def main():
    parser = argparse.ArgumentParser(description="Pagamo map battle bot")
    parser.add_argument("--hex-x", type=int, default=int(os.getenv("HEX_X", "-5121")),
                        help="Starting hex X coordinate (one of your own hexes)")
    parser.add_argument("--hex-y", type=int, default=int(os.getenv("HEX_Y", "-1450")),
                        help="Starting hex Y coordinate")
    parser.add_argument("--gc-id", type=int, default=int(_DEFAULT_GC_ID),
                        help="Your own game character ID (MY_GC_ID in .env)")
    parser.add_argument("--type", dest="battle_type", default="attack",
                        choices=["attack", "train"])
    parser.add_argument("--repeat", type=int, default=1,
                        help="Number of battles to run")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-scan nearby hexes to find enemy targets (attack mode)")
    parser.add_argument("--radius", type=int, default=5,
                        help="Scan radius for --auto mode (default 5)")
    args = parser.parse_args()

    if not args.gc_id:
        raise SystemExit("Set MY_GC_ID in .env (your game character ID)")

    account = os.getenv("PAGAMO_ACCOUNT", "")
    password = os.getenv("PAGAMO_PASSWORD", "")
    if not account or not password:
        raise SystemExit("Set PAGAMO_ACCOUNT and PAGAMO_PASSWORD in .env")

    # In attack mode, always enable auto-scan (own territory → scan automatically)
    auto_scan = args.auto or args.battle_type == "attack"

    session = login(account, password)

    wins = 0
    for i in range(args.repeat):
        if args.repeat > 1:
            print(f"\n=== Battle {i+1}/{args.repeat} ===")
        won = run_battle(
            session,
            hex_x=args.hex_x,
            hex_y=args.hex_y,
            own_gc_id=args.gc_id,
            battle_type=args.battle_type,
            auto_scan=auto_scan,
            scan_radius=args.radius,
        )
        if won:
            wins += 1

    if args.repeat > 1:
        print(f"\n=== Final: {wins}/{args.repeat} wins ===")


if __name__ == "__main__":
    main()
