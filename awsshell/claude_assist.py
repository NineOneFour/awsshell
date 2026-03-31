"""
Claude inline assistant — translates natural language queries into awsshell commands.

API key is stored in ~/.awsshell_config (JSON).
Falls back to ANTHROPIC_API_KEY environment variable if no stored key.
"""

import json
import os
from pathlib import Path

_CONFIG_FILE = Path.home() / ".awsshell_config"

_SYSTEM_PROMPT = """\
You are an AWS CLI assistant embedded in awsshell, a shell that omits the 'aws' prefix.

Rules:
- Respond with ONLY the exact command to run — no explanation, no markdown, no backticks, no punctuation.
- Do NOT include the 'aws' prefix. Commands go directly to awsshell.
- Use awsshell built-ins where appropriate (e.g. 's3 ls' not 'aws s3 ls', 'whoami' not 'sts get-caller-identity').
- If the request is ambiguous, choose the most common/safe interpretation.
- If you cannot express the request as a single shell command, respond with exactly: UNSUPPORTED

Available awsshell built-ins (use these instead of the raw aws cli equivalents):
  whoami                                   Show identity + IAM policies
  profiles                                 List configured profiles
  use <profile>                            Switch profile
  region [name|clear]                      Show/set region override
  format [json|table|text|yaml|clear]      Show/set output format
  s3 connect <bucket>                      Connect to an S3 bucket
  s3 disconnect                            Disconnect from S3 bucket
  s3 ls [prefix] [--all] [--max N]         List objects in connected bucket
  s3 upload <local-path> [key]             Upload a file
  s3 download <key> [local-path]           Download a file
  iam users|groups|roles [prefix]          List IAM resources
  iam user|group|role <name>               Show full details
  iam keys [username]                      List access keys
  iam rotate-key                           Rotate your own access key
  iam simulate <arn> <action> [resource]   Check permission
  iam who-can <action> [resource]          Find who can perform an action

For everything else, use the AWS CLI service and subcommand without the 'aws' prefix.
Examples: 'ec2 describe-instances', 'lambda list-functions', 'ecs list-clusters'"""


def _load_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_config(cfg: dict) -> None:
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    _CONFIG_FILE.chmod(0o600)


def get_api_key() -> str | None:
    cfg = _load_config()
    return cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")


def set_api_key(key: str) -> None:
    cfg = _load_config()
    cfg["anthropic_api_key"] = key
    _save_config(cfg)


def clear_api_key() -> None:
    cfg = _load_config()
    cfg.pop("anthropic_api_key", None)
    _save_config(cfg)


def ask(query: str, profile: str, region: str | None, is_danger: bool) -> str | None:
    """
    Send a natural language query to Claude and return the suggested awsshell command.
    Returns None if no API key is set, on error, or if the request is unsupported.
    """
    api_key = get_api_key()
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        print("The 'anthropic' package is not installed.")
        print("Install it with: pip install anthropic")
        return None

    context_lines = [
        f"Current AWS profile: {profile}",
        f"Current region: {region or 'default (from profile/environment)'}",
    ]
    if is_danger:
        context_lines.append(
            "WARNING: This is a PRODUCTION account. Strongly prefer read-only commands."
        )
    context = "\n".join(context_lines)

    client = anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"{context}\n\nRequest: {query}",
                }
            ],
        )
        result = message.content[0].text.strip()
        if result == "UNSUPPORTED":
            print("  Claude couldn't translate that into a single command.")
            return None
        return result
    except anthropic.AuthenticationError:
        print("  Invalid Anthropic API key. Run 'claudekey set' to update it.")
        return None
    except Exception as e:
        print(f"  Claude API error: {e}")
        return None
