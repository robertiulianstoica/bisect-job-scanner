"""Drop old advert texts, keeping the postings as history.

    .venv/bin/python -m scanner.prune --texts-older-than 180   # days since last listed

Title, company, location, dates, pay and stack stay in postings; only the
text in posting_texts goes. Run VACUUM afterwards to give the space back.
"""

from __future__ import annotations

import argparse

from scanner.settings import load_config
from scanner.state import State


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--texts-older-than", type=int, required=True, metavar="DAYS")
    parser.add_argument("--vacuum", action="store_true", help="give the freed space back to the disk")
    args = parser.parse_args(argv)
    config = load_config()
    state = State(config["run"]["state_path"])
    print(f"{state.drop_old_texts(args.texts_older_than)} advert texts dropped")
    if args.vacuum:
        state.db.execute("vacuum")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
