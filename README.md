# awsshell

An interactive shell for the AWS CLI. Drop the `aws` prefix and get tab completion, profile switching, an S3 helper, IAM inspection tools, and an optional Claude-powered natural language assistant — all in one REPL.

## Features

- **No `aws` prefix** — type `s3 ls`, `ec2 describe-instances`, etc. directly
- **Tab completion** — AWS services, subcommands, and flags
- **Profile & region management** — switch profiles and set a region override mid-session
- **Coloured prompt** — shows active profile (red for production accounts), region, and working directory
- **S3 helper** — persistent bucket connection with `upload`, `download`, and `ls` commands
- **IAM inspector** — list users/groups/roles, inspect policies, check permissions, find who can perform an action
- **Claude assistant** *(optional)* — ask questions in plain English and have a command run for you

## Requirements

- Python 3.10+
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) installed and on `PATH`
- AWS credentials configured (via `aws configure`, environment variables, or an IAM role)

## Installation

### From source (recommended)

Requires [pipx](https://pipx.pypa.io/stable/installation/).

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/awsshell.git
cd awsshell

# 2. Install with pipx (includes the Claude assistant)
pipx install ".[claude]"
```

This installs `awsshell` into an isolated environment and puts it on your `PATH`.

## Usage

```bash
awsshell
# or start with a specific profile:
awsshell --profile my-profile
```

### Built-in commands

| Command | Description |
|---|---|
| `whoami` | Show current identity and attached IAM policies |
| `profiles` | List all configured AWS profiles |
| `use <profile>` | Switch to a named profile |
| `add-profile` | Add a new AWS profile interactively |
| `region [name\|clear]` | Show or set a region override |
| `format [json\|table\|text\|clear]` | Show or set default output format |
| `alias [name [expansion...]]` | Show or define command aliases |
| `unalias <name>` | Remove an alias |
| `cd`, `pwd`, `ls` | Filesystem navigation |
| `clear` | Clear the terminal |
| `help` | Show all commands |
| `exit` / `quit` / Ctrl-D | Exit the shell |

### S3 helper

```
s3 connect <bucket>                 Connect to a bucket
s3 ls [prefix] [--all] [--max N]   List objects
s3 upload <local-path> [key]        Upload a file
s3 download <key> [local-path]      Download a file
s3 disconnect                       Drop the connection
```

### IAM commands

```
iam users|groups|roles [prefix]          List IAM resources
iam user|group|role <name>               Full detail: policies, members, trust
iam keys [username]                      List access keys
iam rotate-key                           Rotate your own access key
iam simulate <arn> <action> [resource]   Check if a principal can perform an action
iam who-can <action> [resource]          Find all principals that can perform an action
```

### Claude assistant

Requires an Anthropic API key.

```
claudekey set       Save your Anthropic API key
claudekey clear     Remove the stored key
claudekey           Show key status

? list all my S3 buckets
? show running EC2 instances in us-east-1
? who has permission to delete S3 objects
```

The assistant translates your question into an awsshell command and runs it. On production accounts (profiles marked as danger) it will prefer read-only commands.

## Development

```bash
pip install ".[dev]"
pytest
```

## License

MIT
