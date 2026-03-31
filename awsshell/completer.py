import os
import subprocess
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion

from awsshell import profiles
from awsshell.builtins import BUILTINS, _FORMAT_OPTIONS, _S3_SUBCOMMANDS, list_aliases
from awsshell.iam import _IAM_SUBCOMMANDS, list_groupnames, list_rolenames, list_usernames

_REGIONS = [
    "af-south-1", "ap-east-1", "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ap-south-1", "ap-south-2", "ap-southeast-1", "ap-southeast-2", "ap-southeast-3",
    "ap-southeast-4", "ca-central-1", "ca-west-1", "eu-central-1", "eu-central-2",
    "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-2", "eu-west-3",
    "il-central-1", "me-central-1", "me-south-1", "sa-east-1",
    "us-east-1", "us-east-2", "us-gov-east-1", "us-gov-west-1",
    "us-west-1", "us-west-2",
]


def _path_completions(partial: str):
    """Yield filesystem path candidates for a partial path string."""
    if partial.startswith("~"):
        partial = str(Path.home()) + partial[1:]

    path = Path(partial)
    if partial.endswith("/") or partial == "":
        directory = path if path.is_dir() else path.parent
        prefix = partial
    else:
        directory = path.parent
        prefix = partial

    try:
        for entry in sorted(directory.iterdir(), key=lambda e: e.name.lower()):
            candidate = str(entry) + ("/" if entry.is_dir() else "")
            if candidate.startswith(prefix) or str(entry).startswith(prefix):
                yield candidate
    except (PermissionError, FileNotFoundError):
        pass


def _aws_cli_completions(text_before_cursor: str) -> list[str]:
    """Use aws_completer to get completions for the current input."""
    comp_line = "aws " + text_before_cursor
    comp_point = str(len(comp_line))
    env = os.environ.copy()
    env["COMP_LINE"] = comp_line
    env["COMP_POINT"] = comp_point
    try:
        result = subprocess.run(
            ["aws_completer"],
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return [c.rstrip() for c in result.stdout.splitlines() if c.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def _s3_bucket_names() -> list[str]:
    """Fetch S3 bucket names for completion (best-effort)."""
    try:
        profile = profiles.current_profile()
        import boto3
        session = boto3.Session(profile_name=None if profile == "default" else profile)
        client = session.client("s3")
        resp = client.list_buckets()
        return [b["Name"] for b in resp.get("Buckets", [])]
    except Exception:
        return []


class AwsShellCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()
        ends_with_space = text.endswith(" ")

        # Natural language query — no completion
        if text.lstrip().startswith("?"):
            return

        builtin_names = list(BUILTINS.keys()) + ["s3", "iam", "ask"]

        # ── First word ────────────────────────────────────────────────────────
        if len(words) == 0 or (len(words) == 1 and not ends_with_space):
            partial = words[0] if words else ""
            seen: set[str] = set()

            # Built-ins + aliases
            for name in builtin_names + list(list_aliases().keys()):
                if name.startswith(partial) and name not in seen:
                    seen.add(name)
                    yield Completion(name, start_position=-len(partial))

            # AWS CLI services
            for c in _aws_cli_completions(partial):
                if c and c not in seen:
                    seen.add(c)
                    yield Completion(c, start_position=-len(partial))
            return

        cmd = words[0].lower()

        # ── `use <profile>` ───────────────────────────────────────────────────
        if cmd == "use" and (len(words) == 1 or (len(words) == 2 and not ends_with_space)):
            partial = words[1] if len(words) == 2 else ""
            for p in profiles.list_profiles():
                if p["name"].startswith(partial):
                    yield Completion(p["name"], start_position=-len(partial))
            return

        # ── `region [value]` ──────────────────────────────────────────────────
        if cmd == "region" and (len(words) == 1 or (len(words) == 2 and not ends_with_space)):
            partial = words[1] if len(words) == 2 else ""
            for r in _REGIONS + ["clear"]:
                if r.startswith(partial):
                    yield Completion(r, start_position=-len(partial))
            return

        # ── `format [value]` ──────────────────────────────────────────────────
        if cmd == "format" and (len(words) == 1 or (len(words) == 2 and not ends_with_space)):
            partial = words[1] if len(words) == 2 else ""
            for f in _FORMAT_OPTIONS + ["clear"]:
                if f.startswith(partial):
                    yield Completion(f, start_position=-len(partial))
            return

        # ── `unalias <name>` ──────────────────────────────────────────────────
        if cmd == "unalias" and (len(words) == 1 or (len(words) == 2 and not ends_with_space)):
            partial = words[1] if len(words) == 2 else ""
            for name in list_aliases():
                if name.startswith(partial):
                    yield Completion(name, start_position=-len(partial))
            return

        # ── `s3 <subcommand>` ─────────────────────────────────────────────────
        if cmd == "s3" and (len(words) == 1 or (len(words) == 2 and not ends_with_space)):
            partial = words[1] if len(words) == 2 else ""
            for sub in _S3_SUBCOMMANDS:
                if sub.startswith(partial):
                    yield Completion(sub, start_position=-len(partial))
            return

        # ── `s3 connect <bucket>` ─────────────────────────────────────────────
        if (
            cmd == "s3"
            and len(words) >= 2
            and words[1] == "connect"
            and (len(words) == 2 or (len(words) == 3 and not ends_with_space))
        ):
            partial = words[2] if len(words) == 3 else ""
            for bucket in _s3_bucket_names():
                if bucket.startswith(partial):
                    yield Completion(bucket, start_position=-len(partial))
            return

        # ── `iam <subcommand>` ────────────────────────────────────────────────
        if cmd == "iam" and (len(words) == 1 or (len(words) == 2 and not ends_with_space)):
            partial = words[1] if len(words) == 2 else ""
            for sub in _IAM_SUBCOMMANDS:
                if sub.startswith(partial):
                    yield Completion(sub, start_position=-len(partial))
            return

        # ── `iam user/keys <username>` ────────────────────────────────────────
        if (
            cmd == "iam"
            and len(words) >= 2
            and words[1] in ("user", "keys")
            and (len(words) == 2 or (len(words) == 3 and not ends_with_space))
        ):
            partial = words[2] if len(words) == 3 else ""
            for name in list_usernames():
                if name.startswith(partial):
                    yield Completion(name, start_position=-len(partial))
            return

        # ── `iam group <groupname>` ───────────────────────────────────────────
        if (
            cmd == "iam"
            and len(words) >= 2
            and words[1] == "group"
            and (len(words) == 2 or (len(words) == 3 and not ends_with_space))
        ):
            partial = words[2] if len(words) == 3 else ""
            for name in list_groupnames():
                if name.startswith(partial):
                    yield Completion(name, start_position=-len(partial))
            return

        # ── `iam role <rolename>` ─────────────────────────────────────────────
        if (
            cmd == "iam"
            and len(words) >= 2
            and words[1] == "role"
            and (len(words) == 2 or (len(words) == 3 and not ends_with_space))
        ):
            partial = words[2] if len(words) == 3 else ""
            for name in list_rolenames():
                if name.startswith(partial):
                    yield Completion(name, start_position=-len(partial))
            return

        # ── Path completion: cd, ls, s3 upload ───────────────────────────────
        sub = words[1] if len(words) > 1 else ""
        is_path_context = (
            (cmd in ("cd", "ls") and (len(words) == 2 or (len(words) == 1 and ends_with_space)))
            or (cmd == "s3" and sub == "upload" and (len(words) == 3 or (len(words) == 2 and ends_with_space)))
        )
        if is_path_context:
            partial = words[-1] if not ends_with_space else ""
            for candidate in _path_completions(partial):
                yield Completion(candidate, start_position=-len(partial))
            return

        # ── AWS CLI completion for everything else ────────────────────────────
        if cmd not in builtin_names:
            last_word = words[-1] if not ends_with_space else ""
            for c in _aws_cli_completions(text):
                if c:
                    yield Completion(c, start_position=-len(last_word))
