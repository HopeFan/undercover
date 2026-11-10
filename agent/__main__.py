"""Work the queue with the UnderCover Agent: uv run -m agent [CLM-1001]"""

import sys

from agent.main import work_claim, work_queue


def main(args: list[str]) -> None:
    """Work the claim named on the command line, or every waiting claim."""
    if args:
        print(work_claim(args[0]))
    else:
        work_queue()


if __name__ == "__main__":
    main(sys.argv[1:])
