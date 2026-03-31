import argparse
import sys

from awsshell.shell import run


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="awsshell",
        description="Interactive AWS CLI shell — no 'aws' prefix needed.",
    )
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="Start with this named AWS profile active",
    )
    args = parser.parse_args()

    try:
        run(initial_profile=args.profile)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)


if __name__ == "__main__":
    main()
