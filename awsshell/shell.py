import os
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from awsshell import profiles
from awsshell.builtins import dispatch, expand_alias
from awsshell.completer import AwsShellCompleter
from awsshell import runner

HISTORY_FILE = Path.home() / ".awsshell_history"

STYLE = Style.from_dict({
    "prompt.profile.danger": "bold ansired",
    "prompt.profile.safe": "bold ansigreen",
    "prompt.region": "ansicyan",
    "prompt.bracket": "ansigray",
    "prompt.cwd": "ansiyellow",
})


def _short_cwd() -> str:
    """Return cwd as ~/... relative to home when possible, max 40 chars."""
    try:
        rel = "~/" + str(Path.cwd().relative_to(Path.home()))
    except ValueError:
        rel = str(Path.cwd())
    if len(rel) > 40:
        parts = Path(rel).parts
        rel = os.path.join(parts[0], "…", *parts[-2:])
    return rel


def _build_prompt() -> HTML:
    profile = profiles.current_profile()
    danger = profiles.is_danger(profile)
    cls = "prompt.profile.danger" if danger else "prompt.profile.safe"
    cwd = _short_cwd()
    region = profiles.current_region()
    region_part = f' <prompt.region>({region})</prompt.region>' if region else ''
    return HTML(
        f'<ansigray>\uf270</ansigray> '
        f'[<{cls}>{profile}</{cls}>]'
        f'{region_part}'
        f' <prompt.cwd>{cwd}</prompt.cwd>'
        f'<ansigray>> </ansigray>'
    )


def run(initial_profile: str | None = None) -> None:
    if initial_profile:
        profiles.set_profile(initial_profile)

    session: PromptSession = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        completer=AwsShellCompleter(),
        style=STYLE,
        complete_while_typing=False,
    )

    print("awsshell  |  type 'help' for built-in commands, Ctrl-D to exit\n")

    while True:
        try:
            user_input = session.prompt(_build_prompt).strip()
        except KeyboardInterrupt:
            continue
        except EOFError:
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Goodbye.")
            break

        if user_input.lower() == "help":
            _print_help()
            continue

        user_input = expand_alias(user_input)

        if not dispatch(user_input):
            runner.run(user_input)


def _print_help() -> None:
    print("""
Built-in commands:
  whoami                              Show current identity and attached IAM policies
  profiles                            List all configured AWS profiles
  use <profile>                       Switch to a named profile
  add-profile                         Add a new AWS profile interactively
  region [name|clear]                 Show or set a region override
  format [json|table|text|clear]      Show or set default output format
  alias [name [expansion...]]         Show or define command aliases
  unalias <name>                      Remove an alias
  clear                               Clear the terminal screen
  help                                Show this message
  exit / quit                         Exit the shell

Filesystem navigation:
  cd [path]                           Change directory (defaults to home)
  pwd                                 Print current directory
  ls [path]                           List directory contents

S3 helper commands (persistent connection):
  s3 connect <bucket>                 Connect to a bucket
  s3 disconnect                       Drop the current connection
  s3 upload <local-path> [key]        Upload a file (key defaults to filename)
  s3 download <key> [local-path]      Download a file (path defaults to ./<key>)
  s3 ls [prefix] [--all] [--max N]   List objects in connected bucket

IAM commands:
  iam users [prefix]                  List IAM users
  iam groups [prefix]                 List IAM groups
  iam roles [prefix]                  List IAM roles
  iam user <name>                     Full detail: policies, groups, keys, MFA
  iam group <name>                    Members + policies
  iam role <name>                     Trust policy + attached policies
  iam keys [username]                 List access keys (defaults to current caller)
  iam rotate-key                      Create a new key, optionally delete the old one
  iam simulate <principal-arn> <action> [resource]
                                      Check if a principal is allowed an action
  iam who-can <action> [resource]     Find all users/roles that can perform an action

Claude inline assistant (requires Anthropic API key):
  claudekey set                          Save your Anthropic API key
  claudekey clear                        Remove stored API key
  claudekey                              Show API key status
  ? <question>                        Ask Claude to run an AWS command for you
  ask <question>                      Same as ?

Examples:
  ? list all my S3 buckets
  ? show running EC2 instances in us-east-1
  ? who has permission to delete S3 objects

Any other input is passed directly to the AWS CLI (no 'aws' prefix needed).
Tab completion is available for AWS CLI services, subcommands, and flags.

Examples:
  s3 ls                               (AWS CLI — lists all buckets)
  ec2 describe-instances --region us-east-1
  sts get-caller-identity
  region us-west-2                    (set region override for all commands)
  format json                         (use JSON output by default)
  alias di ec2 describe-instances     (define a shorthand alias)
""")
