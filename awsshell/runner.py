import os
import shlex
import subprocess

from awsshell import profiles

_format: str | None = None

_DESTRUCTIVE_KEYWORDS = {
    "delete", "terminate", "destroy", "remove", "stop",
    "kill", "drop", "detach", "revoke", "deregister",
}


def set_format(fmt: str | None) -> None:
    global _format
    _format = fmt


def current_format() -> str | None:
    return _format


def _is_destructive(args: list[str]) -> bool:
    return any(
        any(kw in arg.lower() for kw in _DESTRUCTIVE_KEYWORDS)
        for arg in args
    )


def run(user_input: str) -> int:
    """Prepend 'aws' and execute the command, returning the exit code."""
    args = shlex.split(user_input)
    if not args:
        return 0

    env = os.environ.copy()
    profile = profiles.current_profile()
    if profile != "default":
        env["AWS_PROFILE"] = profile
    elif "AWS_PROFILE" in env:
        # Don't let a stale env var override an explicit switch to default
        del env["AWS_PROFILE"]

    region = profiles.current_region()
    if region:
        env["AWS_DEFAULT_REGION"] = region

    # Inject output format if set and not already specified
    if _format and "--output" not in args:
        args += ["--output", _format]

    # Production guard — confirm before destructive commands on danger profiles
    if profiles.is_danger(profile) and _is_destructive(args):
        try:
            answer = input(
                f"  ⚠  Production profile '{profile}' — are you sure? [y/N] "
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 0
        if answer != "y":
            print("Aborted.")
            return 0

    result = subprocess.run(["aws"] + args, env=env)
    return result.returncode
