
from __future__ import annotations

import argparse
from .service import games_service


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["update"])
    parser.add_argument("--game", required=True)
    parser.add_argument("--platform", default="")
    args = parser.parse_args()

    game = games_service.find_game(args.game, platform=args.platform)
    message, _ = games_service.update(game)
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
