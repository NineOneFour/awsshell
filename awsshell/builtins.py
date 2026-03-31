import configparser
import getpass
import os
import shlex
from pathlib import Path

import boto3
import botocore.exceptions

from awsshell import profiles

_AWS_CREDENTIALS = Path.home() / ".aws" / "credentials"

_FORMAT_OPTIONS = ["json", "table", "text", "yaml", "yaml-stream"]


def _boto_session() -> boto3.Session:
    profile = profiles.current_profile()
    return boto3.Session(profile_name=None if profile == "default" else profile)


# ── clear ─────────────────────────────────────────────────────────────────────

def cmd_clear(_args: list[str]) -> None:
    print("\033[H\033[2J", end="", flush=True)


# ── profiles ──────────────────────────────────────────────────────────────────

def cmd_profiles(_args: list[str]) -> None:
    all_profiles = profiles.list_profiles()
    current = profiles.current_profile()
    for p in all_profiles:
        marker = "*" if p["name"] == current else " "
        region = f"  ({p['region']})" if p["region"] else ""
        danger = "  ⚠ PRODUCTION" if profiles.is_danger(p["name"]) else ""
        print(f"  {marker} {p['name']}{region}{danger}")


# ── use ───────────────────────────────────────────────────────────────────────

def cmd_use(args: list[str]) -> None:
    if not args:
        print("Usage: use <profile>")
        return

    name = args[0]
    if not profiles.set_profile(name):
        print(f"Profile '{name}' not found. Run 'profiles' to list available profiles.")
        return

    # Drop S3 connection — new account may not have access to same bucket
    if s3_state["bucket"] is not None:
        bucket = s3_state["bucket"]
        s3_state["bucket"] = None
        s3_state["client"] = None
        print(
            f"Disconnected from S3 bucket '{bucket}' "
            f"(switching accounts — reconnect with: s3 connect {bucket})"
        )

    print(f"Switched to: {name}")
    cmd_whoami([])


# ── add-profile ───────────────────────────────────────────────────────────────

def cmd_add_profile(_args: list[str]) -> None:
    print("Add a new AWS profile\n")

    name = input("Profile name: ").strip()
    if not name:
        print("Aborted.")
        return

    existing = {p["name"] for p in profiles.list_profiles()}
    if name in existing:
        confirm = input(f"Profile '{name}' already exists. Overwrite? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    print("\nAuth type:")
    print("  1. Static credentials (access key + secret)")
    print("  2. Assume role (role ARN + source profile)")
    auth_choice = input("\nChoice [1/2]: ").strip()

    if auth_choice == "1":
        _add_profile_static(name)
    elif auth_choice == "2":
        _add_profile_role(name)
    else:
        print("Invalid choice. Aborted.")


def _add_profile_static(name: str) -> None:
    access_key = input("AWS Access Key ID: ").strip()
    if not access_key:
        print("Aborted.")
        return
    secret_key = getpass.getpass("AWS Secret Access Key: ").strip()
    if not secret_key:
        print("Aborted.")
        return
    region = input("Default region (leave blank to skip): ").strip()

    _write_config(name, region=region or None)
    _write_credentials(name, access_key, secret_key)
    print(f"\nProfile '{name}' added. Use 'use {name}' to switch to it.")


def _add_profile_role(name: str) -> None:
    role_arn = input("Role ARN: ").strip()
    if not role_arn:
        print("Aborted.")
        return

    available = [p["name"] for p in profiles.list_profiles()]
    print(f"Available source profiles: {', '.join(available)}")
    source = input("Source profile: ").strip()
    if not source:
        print("Aborted.")
        return
    region = input("Default region (leave blank to skip): ").strip()

    _write_config(name, region=region or None, role_arn=role_arn, source_profile=source)
    print(f"\nProfile '{name}' added. Use 'use {name}' to switch to it.")


def _write_config(
    name: str,
    region: str | None = None,
    role_arn: str | None = None,
    source_profile: str | None = None,
) -> None:
    config = configparser.ConfigParser()
    config.read(profiles._AWS_CONFIG)

    section = "default" if name == "default" else f"profile {name}"
    if not config.has_section(section) and section != "default":
        config.add_section(section)

    if region:
        config.set(section, "region", region)
    if role_arn:
        config.set(section, "role_arn", role_arn)
    if source_profile:
        config.set(section, "source_profile", source_profile)

    profiles._AWS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(profiles._AWS_CONFIG, "w") as f:
        config.write(f)


def _write_credentials(name: str, access_key: str, secret_key: str) -> None:
    creds = configparser.ConfigParser()
    creds.read(_AWS_CREDENTIALS)

    if not creds.has_section(name):
        creds.add_section(name)

    creds.set(name, "aws_access_key_id", access_key)
    creds.set(name, "aws_secret_access_key", secret_key)

    _AWS_CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    with open(_AWS_CREDENTIALS, "w") as f:
        creds.write(f)


# ── whoami ────────────────────────────────────────────────────────────────────

def _parse_arn(arn: str) -> dict:
    """Return type and name from an ARN."""
    parts = arn.split(":")
    resource = parts[-1]  # e.g. user/alice  or  assumed-role/RoleName/session
    resource_parts = resource.split("/")
    kind = resource_parts[0]
    return {
        "kind": kind,
        "name": resource_parts[1] if len(resource_parts) > 1 else None,
        "session": resource_parts[2] if len(resource_parts) > 2 else None,
    }


def _fetch_user_policies(iam, username: str) -> None:
    try:
        attached = iam.list_attached_user_policies(UserName=username)
        inline = iam.list_user_policies(UserName=username)
        groups = iam.list_groups_for_user(UserName=username)

        print("\nAttached Policies:")
        for p in attached.get("AttachedPolicies", []):
            kind = "AWS managed" if ":aws:policy/" in p["PolicyArn"] else "customer managed"
            print(f"  - {p['PolicyArn']}  [{kind}]")
        if not attached.get("AttachedPolicies"):
            print("  (none)")

        print("\nInline Policies:")
        for name in inline.get("PolicyNames", []):
            print(f"  - {name}")
        if not inline.get("PolicyNames"):
            print("  (none)")

        print("\nGroups:")
        for g in groups.get("Groups", []):
            print(f"  - {g['GroupName']}")
        if not groups.get("Groups"):
            print("  (none)")

    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "AccessDenied":
            print("\n  [AccessDenied] Insufficient permissions to list IAM policies.")
        else:
            raise


def _fetch_role_policies(iam, role_name: str) -> None:
    try:
        attached = iam.list_attached_role_policies(RoleName=role_name)
        inline = iam.list_role_policies(RoleName=role_name)

        print("\nAttached Role Policies:")
        for p in attached.get("AttachedPolicies", []):
            kind = "AWS managed" if ":aws:policy/" in p["PolicyArn"] else "customer managed"
            print(f"  - {p['PolicyArn']}  [{kind}]")
        if not attached.get("AttachedPolicies"):
            print("  (none)")

        print("\nInline Role Policies:")
        for name in inline.get("PolicyNames", []):
            print(f"  - {name}")
        if not inline.get("PolicyNames"):
            print("  (none)")

    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "AccessDenied":
            print("\n  [AccessDenied] Insufficient permissions to list role policies.")
        else:
            raise


def cmd_whoami(_args: list[str]) -> None:
    session = _boto_session()
    sts = session.client("sts")

    try:
        identity = sts.get_caller_identity()
    except botocore.exceptions.ClientError as e:
        print(f"Error: {e}")
        return
    except botocore.exceptions.NoCredentialsError:
        print("No credentials found for this profile.")
        return

    arn = identity["Arn"]
    parsed = _parse_arn(arn)

    print(f"\nAccount:  {identity['Account']}")
    print(f"ARN:      {arn}")

    if parsed["kind"] == "root":
        print("Type:     ROOT ACCOUNT — avoid using root credentials!")
        return

    if parsed["kind"] == "user":
        print(f"Type:     IAM User ({parsed['name']})")
        iam = session.client("iam")
        _fetch_user_policies(iam, parsed["name"])

    elif parsed["kind"] == "assumed-role":
        session_name = parsed["session"] or ""
        print(f"Type:     Assumed Role ({parsed['name']}, session: {session_name})")
        iam = session.client("iam")
        _fetch_role_policies(iam, parsed["name"])

    else:
        print(f"Type:     {parsed['kind']}")

    print()


# ── filesystem navigation ─────────────────────────────────────────────────────

def cmd_cd(args: list[str]) -> None:
    path = args[0] if args else str(Path.home())
    try:
        os.chdir(path)
    except FileNotFoundError:
        print(f"cd: no such directory: {path}")
    except NotADirectoryError:
        print(f"cd: not a directory: {path}")
    except PermissionError:
        print(f"cd: permission denied: {path}")


def cmd_pwd(_args: list[str]) -> None:
    print(os.getcwd())


def cmd_ls(args: list[str]) -> None:
    path = args[0] if args else "."
    try:
        entries = sorted(
            Path(path).iterdir(),
            key=lambda e: (not e.is_dir(), e.name.lower()),
        )
    except FileNotFoundError:
        print(f"ls: no such directory: {path}")
        return
    except NotADirectoryError:
        print(f"ls: not a directory: {path}")
        return
    except PermissionError:
        print(f"ls: permission denied: {path}")
        return

    for entry in entries:
        if entry.is_dir():
            print(f"  {entry.name}/")
        else:
            try:
                size = entry.stat().st_size
            except (FileNotFoundError, OSError):
                print(f"  {entry.name:<50}  {'(broken link)':>8}")
                continue
            if size >= 1024 * 1024:
                size_str = f"{size / 1024 / 1024:.1f}M"
            elif size >= 1024:
                size_str = f"{size / 1024:.1f}K"
            else:
                size_str = f"{size}B"
            print(f"  {entry.name:<50}  {size_str:>8}")


# ── region ────────────────────────────────────────────────────────────────────

def cmd_region(args: list[str]) -> None:
    if not args:
        r = profiles.current_region()
        print(f"Region: {r if r else '(not set — using profile/environment default)'}")
        return
    if args[0].lower() in ("clear", "none", "off"):
        profiles.set_region(None)
        print("Region override cleared.")
        return
    profiles.set_region(args[0])
    print(f"Region set to: {args[0]}")


# ── format ────────────────────────────────────────────────────────────────────

def cmd_format(args: list[str]) -> None:
    from awsshell import runner
    if not args:
        fmt = runner.current_format()
        print(f"Output format: {fmt if fmt else '(not set — using AWS default)'}")
        return
    if args[0].lower() in ("clear", "none", "off"):
        runner.set_format(None)
        print("Output format cleared.")
        return
    if args[0].lower() not in _FORMAT_OPTIONS:
        print(f"Invalid format. Choose from: {', '.join(_FORMAT_OPTIONS)}")
        return
    runner.set_format(args[0].lower())
    print(f"Output format set to: {args[0].lower()}")


# ── alias ─────────────────────────────────────────────────────────────────────

_aliases: dict[str, str] = {}


def cmd_alias(args: list[str]) -> None:
    if not args:
        if not _aliases:
            print("  (no aliases defined)")
        for name, expansion in sorted(_aliases.items()):
            print(f"  alias {name}='{expansion}'")
        return
    if len(args) == 1:
        name = args[0]
        if name in _aliases:
            print(f"  alias {name}='{_aliases[name]}'")
        else:
            print(f"No alias '{name}'.")
        return
    name = args[0]
    expansion = " ".join(args[1:])
    _aliases[name] = expansion
    print(f"  alias {name}='{expansion}'")


def cmd_unalias(args: list[str]) -> None:
    if not args:
        print("Usage: unalias <name>")
        return
    name = args[0]
    if name in _aliases:
        del _aliases[name]
        print(f"Removed alias '{name}'.")
    else:
        print(f"No alias '{name}'.")


def expand_alias(user_input: str) -> str:
    """Expand a leading alias if one matches the first word."""
    try:
        parts = shlex.split(user_input)
    except ValueError:
        return user_input
    if parts and parts[0] in _aliases:
        expansion = _aliases[parts[0]]
        rest = parts[1:]
        return expansion + (" " + shlex.join(rest) if rest else "")
    return user_input


def list_aliases() -> dict[str, str]:
    return dict(_aliases)


# ── s3 ────────────────────────────────────────────────────────────────────────

s3_state: dict = {"bucket": None, "client": None}

_S3_SUBCOMMANDS = ["connect", "disconnect", "upload", "download", "ls"]


class _S3Progress:
    def __init__(self, label: str, total: int):
        self._label = label
        self._total = total
        self._seen = 0

    def __call__(self, bytes_amount: int):
        self._seen += bytes_amount
        if self._total:
            pct = self._seen / self._total * 100
            print(f"\r  {self._label}: {pct:.1f}%", end="", flush=True)

    def done(self):
        print()


def _require_connection() -> bool:
    if s3_state["bucket"] is None:
        print("No active S3 connection. Use: s3 connect <bucket>")
        return False
    return True


def _s3_connect(args: list[str]) -> None:
    if not args:
        print("Usage: s3 connect <bucket>")
        return
    bucket = args[0]
    session = _boto_session()
    client = session.client("s3")
    try:
        client.head_bucket(Bucket=bucket)
    except botocore.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("403", "AccessDenied"):
            print(f"Access denied to bucket '{bucket}'.")
        elif code in ("404", "NoSuchBucket"):
            print(f"Bucket '{bucket}' does not exist.")
        else:
            print(f"Error connecting to '{bucket}': {e}")
        return
    except botocore.exceptions.NoCredentialsError:
        print("No credentials found for this profile.")
        return
    s3_state["bucket"] = bucket
    s3_state["client"] = client
    print(f"Connected to s3://{bucket}")


def _s3_disconnect() -> None:
    if s3_state["bucket"] is None:
        print("No active S3 connection.")
        return
    bucket = s3_state["bucket"]
    s3_state["bucket"] = None
    s3_state["client"] = None
    print(f"Disconnected from s3://{bucket}")


def _s3_upload(args: list[str]) -> None:
    if not _require_connection():
        return
    if not args:
        print("Usage: s3 upload <local-path> [<s3-key>]")
        return
    local_path = args[0]
    key = args[1] if len(args) > 1 else os.path.basename(local_path)
    if not os.path.isfile(local_path):
        print(f"File not found: {local_path}")
        return

    size = os.path.getsize(local_path)
    progress = _S3Progress(f"Uploading {key}", size)
    try:
        s3_state["client"].upload_file(local_path, s3_state["bucket"], key, Callback=progress)
        progress.done()
        print(f"Uploaded to s3://{s3_state['bucket']}/{key}")
    except botocore.exceptions.ClientError as e:
        print(f"\nUpload failed: {e}")


def _s3_download(args: list[str]) -> None:
    if not _require_connection():
        return
    if not args:
        print("Usage: s3 download <s3-key> [<local-path>]")
        return
    key = args[0]
    local_path = args[1] if len(args) > 1 else os.path.basename(key)

    try:
        meta = s3_state["client"].head_object(Bucket=s3_state["bucket"], Key=key)
        size = meta["ContentLength"]
    except botocore.exceptions.ClientError:
        size = 0

    progress = _S3Progress(f"Downloading {key}", size)
    try:
        s3_state["client"].download_file(s3_state["bucket"], key, local_path, Callback=progress)
        progress.done()
        print(f"Downloaded to {local_path}")
    except botocore.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "404":
            print(f"\nKey not found: {key}")
        else:
            print(f"\nDownload failed: {e}")


def _s3_ls(args: list[str]) -> None:
    show_all = "--all" in args
    args = [a for a in args if a != "--all"]

    max_keys = 100
    if "--max" in args:
        idx = args.index("--max")
        try:
            max_keys = int(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        except (IndexError, ValueError):
            print("Usage: s3 ls [prefix] [--all] [--max N]")
            return

    if not _require_connection():
        return

    prefix = args[0] if args else ""

    try:
        if show_all:
            paginator = s3_state["client"].get_paginator("list_objects_v2")
            pages = paginator.paginate(
                Bucket=s3_state["bucket"],
                **({"Prefix": prefix} if prefix else {}),
            )
            count = 0
            for page in pages:
                for obj in page.get("Contents", []):
                    size_kb = obj["Size"] / 1024
                    print(f"  {obj['Key']:<60}  {size_kb:>8.1f} KB")
                    count += 1
            if count == 0:
                label = f" with prefix '{prefix}'" if prefix else ""
                print(f"  (no objects{label})")
        else:
            kwargs: dict = {"Bucket": s3_state["bucket"], "MaxKeys": max_keys}
            if prefix:
                kwargs["Prefix"] = prefix
            resp = s3_state["client"].list_objects_v2(**kwargs)
            objects = resp.get("Contents", [])
            if not objects:
                label = f" with prefix '{prefix}'" if prefix else ""
                print(f"  (no objects{label})")
                return
            for obj in objects:
                size_kb = obj["Size"] / 1024
                print(f"  {obj['Key']:<60}  {size_kb:>8.1f} KB")
            if resp.get("IsTruncated"):
                print(f"  ... (truncated at {len(objects)}, use --all or --max N to see more)")
    except botocore.exceptions.ClientError as e:
        print(f"Error listing objects: {e}")


def cmd_s3(args: list[str]) -> bool:
    """Handle s3 subcommands. Returns True if handled, False to pass to AWS CLI."""
    if not args:
        print("S3 helper commands:")
        print("  s3 connect <bucket>                     Connect to a bucket")
        print("  s3 disconnect                            Drop the current connection")
        print("  s3 upload <local-path> [key]             Upload a file")
        print("  s3 download <key> [local-path]           Download a file")
        print("  s3 ls [prefix] [--all] [--max N]         List objects in connected bucket")
        return True

    sub = args[0].lower()

    if sub == "connect":
        _s3_connect(args[1:])
        return True
    if sub == "disconnect":
        _s3_disconnect()
        return True
    if sub == "upload":
        _s3_upload(args[1:])
        return True
    if sub == "download":
        _s3_download(args[1:])
        return True
    if sub == "ls" and s3_state["bucket"] is not None:
        _s3_ls(args[1:])
        return True

    # Unknown subcommand or `s3 ls` with no active connection → pass to AWS CLI
    return False


# ── Claude inline assistant ───────────────────────────────────────────────────

def cmd_claudekey(args: list[str]) -> None:
    from awsshell import claude_assist
    sub = args[0].lower() if args else ""

    if sub == "set":
        key = getpass.getpass("Anthropic API key: ").strip()
        if not key:
            print("Aborted.")
            return
        claude_assist.set_api_key(key)
        print("API key saved to ~/.awsshell_config")
        return

    if sub == "clear":
        claude_assist.clear_api_key()
        print("API key cleared.")
        return

    # Show status
    key = claude_assist.get_api_key()
    if key:
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "****"
        print(f"  API key: {masked}  (stored — use 'claudekey clear' to remove)")
    else:
        print("  No API key set. Use 'claudekey set' to add one, or set ANTHROPIC_API_KEY env var.")


def cmd_ask(query: str) -> None:
    query = query.strip()
    if not query:
        print("Usage: ? <what you want to do>")
        print("Example: ? list all my S3 buckets")
        return

    from awsshell import claude_assist, profiles
    key = claude_assist.get_api_key()
    if not key:
        print("  No Anthropic API key configured. Run 'claudekey set' to add one.")
        return

    print("  Thinking...", end="\r", flush=True)
    profile = profiles.current_profile()
    region = profiles.current_region()
    is_danger = profiles.is_danger(profile)

    suggested = claude_assist.ask(query, profile, region, is_danger)
    print("              ", end="\r", flush=True)  # clear "Thinking..."

    if not suggested:
        return

    print(f"  Suggested: {suggested}")
    try:
        answer = input("  Run this? [Y/n] ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Aborted.")
        return

    if answer in ("", "y", "yes"):
        print()
        if not dispatch(suggested):
            from awsshell import runner
            runner.run(suggested)
    else:
        print("  Aborted.")


# ── dispatch ──────────────────────────────────────────────────────────────────

BUILTINS = {
    "profiles": cmd_profiles,
    "use": cmd_use,
    "whoami": cmd_whoami,
    "clear": cmd_clear,
    "add-profile": cmd_add_profile,
    "cd": cmd_cd,
    "pwd": cmd_pwd,
    "ls": cmd_ls,
    "region": cmd_region,
    "format": cmd_format,
    "alias": cmd_alias,
    "unalias": cmd_unalias,
    "claudekey": cmd_claudekey,
}


def dispatch(user_input: str) -> bool:
    """
    Try to handle input as a built-in command.
    Returns True if handled, False if it should be passed to the AWS CLI runner.
    """
    stripped = user_input.strip()

    # Natural language query: `? <query>` or `ask <query>`
    if stripped.startswith("?"):
        cmd_ask(stripped[1:].lstrip())
        return True

    parts = shlex.split(stripped) if stripped else []
    if not parts:
        return True

    cmd = parts[0].lower()

    if cmd == "ask":
        cmd_ask(" ".join(parts[1:]))
        return True

    # s3 is handled specially — some subcommands fall through to the AWS CLI
    if cmd == "s3":
        return cmd_s3(parts[1:])

    if cmd == "iam":
        from awsshell.iam import cmd_iam
        cmd_iam(parts[1:])
        return True

    if cmd in BUILTINS:
        BUILTINS[cmd](parts[1:])
        return True

    return False
