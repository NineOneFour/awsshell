import json
from datetime import datetime, timezone
from urllib.parse import unquote

import boto3
import botocore.exceptions

from awsshell import profiles

_IAM_SUBCOMMANDS = [
    "users", "groups", "roles",
    "user", "group", "role",
    "keys", "rotate-key",
    "simulate", "who-can",
]


def _boto_session() -> boto3.Session:
    profile = profiles.current_profile()
    return boto3.Session(profile_name=None if profile == "default" else profile)


def _iam_client():
    return _boto_session().client("iam")


def _age(dt: datetime) -> str:
    """Human-readable age from a datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    days = delta.days
    if days == 0:
        hours = delta.seconds // 3600
        return f"{hours}h ago" if hours else "just now"
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{days // 365}y ago"


def _handle_error(e: botocore.exceptions.ClientError) -> None:
    code = e.response["Error"]["Code"]
    msg = e.response["Error"]["Message"]
    if code in ("AccessDenied", "AccessDeniedException"):
        print(f"  [AccessDenied] {msg}")
    elif code == "NoSuchEntity":
        print(f"  Not found: {msg}")
    else:
        print(f"  Error ({code}): {msg}")


def _policy_kind(arn: str) -> str:
    return "AWS" if ":aws:policy/" in arn else "customer"


# ── iam users ─────────────────────────────────────────────────────────────────

def _cmd_users(args: list[str]) -> None:
    iam = _iam_client()
    prefix = args[0] if args else ""
    try:
        users = []
        for page in iam.get_paginator("list_users").paginate():
            for u in page["Users"]:
                if not prefix or u["UserName"].lower().startswith(prefix.lower()):
                    users.append(u)
        if not users:
            print("  (no users found)")
            return
        print(f"\n  {'Username':<32}  {'Created':<14}  Password last used")
        print(f"  {'-'*32}  {'-'*14}  {'-'*20}")
        for u in sorted(users, key=lambda x: x["UserName"].lower()):
            created = _age(u["CreateDate"])
            plu = (
                _age(u["PasswordLastUsed"]) if "PasswordLastUsed" in u
                else "never / key-only"
            )
            print(f"  {u['UserName']:<32}  {created:<14}  {plu}")
        print()
    except botocore.exceptions.ClientError as e:
        _handle_error(e)


# ── iam groups ────────────────────────────────────────────────────────────────

def _cmd_groups(args: list[str]) -> None:
    iam = _iam_client()
    prefix = args[0] if args else ""
    try:
        groups = []
        for page in iam.get_paginator("list_groups").paginate():
            for g in page["Groups"]:
                if not prefix or g["GroupName"].lower().startswith(prefix.lower()):
                    groups.append(g)
        if not groups:
            print("  (no groups found)")
            return
        print(f"\n  {'Group name':<40}  Created")
        print(f"  {'-'*40}  {'-'*14}")
        for g in sorted(groups, key=lambda x: x["GroupName"].lower()):
            print(f"  {g['GroupName']:<40}  {_age(g['CreateDate'])}")
        print()
    except botocore.exceptions.ClientError as e:
        _handle_error(e)


# ── iam roles ─────────────────────────────────────────────────────────────────

def _cmd_roles(args: list[str]) -> None:
    iam = _iam_client()
    prefix = args[0] if args else ""
    try:
        roles = []
        for page in iam.get_paginator("list_roles").paginate():
            for r in page["Roles"]:
                if not prefix or r["RoleName"].lower().startswith(prefix.lower()):
                    roles.append(r)
        if not roles:
            print("  (no roles found)")
            return
        print(f"\n  {'Role name':<52}  Created")
        print(f"  {'-'*52}  {'-'*14}")
        for r in sorted(roles, key=lambda x: x["RoleName"].lower()):
            print(f"  {r['RoleName']:<52}  {_age(r['CreateDate'])}")
        print()
    except botocore.exceptions.ClientError as e:
        _handle_error(e)


# ── iam user <name> ───────────────────────────────────────────────────────────

def _cmd_user(args: list[str]) -> None:
    if not args:
        print("Usage: iam user <username>")
        return
    name = args[0]
    iam = _iam_client()
    try:
        u = iam.get_user(UserName=name)["User"]
    except botocore.exceptions.ClientError as e:
        _handle_error(e)
        return

    print(f"\nUser:     {u['UserName']}")
    print(f"ARN:      {u['Arn']}")
    print(f"Created:  {u['CreateDate'].strftime('%Y-%m-%d')}  ({_age(u['CreateDate'])})")
    if "PasswordLastUsed" in u:
        plu = u["PasswordLastUsed"]
        print(f"Password: last used {plu.strftime('%Y-%m-%d')}  ({_age(plu)})")
    else:
        print("Password: never used / key-only access")

    # Attached managed policies
    attached = iam.list_attached_user_policies(UserName=name).get("AttachedPolicies", [])
    print("\nAttached Policies:")
    for p in attached:
        print(f"  - {p['PolicyArn']}  [{_policy_kind(p['PolicyArn'])}]")
    if not attached:
        print("  (none)")

    # Inline policies
    inline = iam.list_user_policies(UserName=name).get("PolicyNames", [])
    print("\nInline Policies:")
    for p in inline:
        print(f"  - {p}")
    if not inline:
        print("  (none)")

    # Groups
    groups = iam.list_groups_for_user(UserName=name).get("Groups", [])
    print("\nGroups:")
    for g in groups:
        print(f"  - {g['GroupName']}")
    if not groups:
        print("  (none)")

    # Access keys
    keys = iam.list_access_keys(UserName=name).get("AccessKeyMetadata", [])
    print("\nAccess Keys:")
    if keys:
        for k in keys:
            try:
                lu = iam.get_access_key_last_used(
                    AccessKeyId=k["AccessKeyId"]
                ).get("AccessKeyLastUsed", {})
                if "LastUsedDate" in lu:
                    svc = lu.get("ServiceName", "")
                    region = lu.get("Region", "")
                    last = _age(lu["LastUsedDate"])
                    detail = f"{last}"
                    if svc and svc != "N/A":
                        detail += f"  via {svc}"
                        if region and region != "N/A":
                            detail += f" ({region})"
                else:
                    detail = "never"
            except Exception:
                detail = "unknown"
            created = _age(k["CreateDate"])
            print(
                f"  {k['AccessKeyId']}  {k['Status']:<10}  "
                f"created {created:<12}  last used: {detail}"
            )
    else:
        print("  (none)")

    # MFA devices
    mfa = iam.list_mfa_devices(UserName=name).get("MFADevices", [])
    print("\nMFA Devices:")
    for m in mfa:
        print(f"  - {m['SerialNumber']}  (enabled {_age(m['EnableDate'])})")
    if not mfa:
        print("  (none)")

    print()


# ── iam group <name> ──────────────────────────────────────────────────────────

def _cmd_group(args: list[str]) -> None:
    if not args:
        print("Usage: iam group <groupname>")
        return
    name = args[0]
    iam = _iam_client()
    try:
        resp = iam.get_group(GroupName=name)
    except botocore.exceptions.ClientError as e:
        _handle_error(e)
        return

    info = resp["Group"]
    members = resp.get("Users", [])
    print(f"\nGroup:    {info['GroupName']}")
    print(f"ARN:      {info['Arn']}")
    print(f"Created:  {info['CreateDate'].strftime('%Y-%m-%d')}  ({_age(info['CreateDate'])})")

    print(f"\nMembers ({len(members)}):")
    for u in sorted(members, key=lambda x: x["UserName"]):
        print(f"  - {u['UserName']}")
    if not members:
        print("  (none)")

    attached = iam.list_attached_group_policies(GroupName=name).get("AttachedPolicies", [])
    print("\nAttached Policies:")
    for p in attached:
        print(f"  - {p['PolicyArn']}  [{_policy_kind(p['PolicyArn'])}]")
    if not attached:
        print("  (none)")

    inline = iam.list_group_policies(GroupName=name).get("PolicyNames", [])
    print("\nInline Policies:")
    for p in inline:
        print(f"  - {p}")
    if not inline:
        print("  (none)")

    print()


# ── iam role <name> ───────────────────────────────────────────────────────────

def _cmd_role(args: list[str]) -> None:
    if not args:
        print("Usage: iam role <rolename>")
        return
    name = args[0]
    iam = _iam_client()
    try:
        r = iam.get_role(RoleName=name)["Role"]
    except botocore.exceptions.ClientError as e:
        _handle_error(e)
        return

    print(f"\nRole:     {r['RoleName']}")
    print(f"ARN:      {r['Arn']}")
    print(f"Created:  {r['CreateDate'].strftime('%Y-%m-%d')}  ({_age(r['CreateDate'])})")
    if r.get("Description"):
        print(f"Desc:     {r['Description']}")
    if r.get("MaxSessionDuration"):
        print(f"Max session: {r['MaxSessionDuration'] // 3600}h")

    # Trust policy — boto3 returns this as an already-decoded dict
    trust = r.get("AssumeRolePolicyDocument", {})
    if isinstance(trust, str):
        trust = json.loads(unquote(trust))
    print("\nTrust Policy (principals that can assume this role):")
    for stmt in trust.get("Statement", []):
        effect = stmt.get("Effect", "Allow")
        principal = stmt.get("Principal", {})
        conditions = stmt.get("Condition", {})
        if isinstance(principal, str):
            print(f"  {effect}: {principal}")
        elif isinstance(principal, dict):
            for kind, val in principal.items():
                vals = [val] if isinstance(val, str) else val
                for v in vals:
                    print(f"  {effect} [{kind}]: {v}")
        if conditions:
            for op, conds in conditions.items():
                for key, val in conds.items():
                    print(f"    Condition — {op}: {key} = {val}")

    attached = iam.list_attached_role_policies(RoleName=name).get("AttachedPolicies", [])
    print("\nAttached Policies:")
    for p in attached:
        print(f"  - {p['PolicyArn']}  [{_policy_kind(p['PolicyArn'])}]")
    if not attached:
        print("  (none)")

    inline = iam.list_role_policies(RoleName=name).get("PolicyNames", [])
    print("\nInline Policies:")
    for p in inline:
        print(f"  - {p}")
    if not inline:
        print("  (none)")

    instance_profiles = iam.list_instance_profiles_for_role(
        RoleName=name
    ).get("InstanceProfiles", [])
    if instance_profiles:
        print("\nInstance Profiles:")
        for ip in instance_profiles:
            print(f"  - {ip['InstanceProfileName']}")

    print()


# ── iam keys ──────────────────────────────────────────────────────────────────

def _cmd_keys(args: list[str]) -> None:
    iam = _iam_client()
    kwargs: dict = {}
    label = "current caller"
    if args:
        kwargs["UserName"] = args[0]
        label = args[0]

    try:
        keys = iam.list_access_keys(**kwargs).get("AccessKeyMetadata", [])
    except botocore.exceptions.ClientError as e:
        _handle_error(e)
        return

    if not keys:
        print(f"  No access keys for {label}.")
        return

    print(f"\nAccess keys for {label}:")
    for k in keys:
        try:
            lu = iam.get_access_key_last_used(
                AccessKeyId=k["AccessKeyId"]
            ).get("AccessKeyLastUsed", {})
            if "LastUsedDate" in lu:
                svc = lu.get("ServiceName", "")
                reg = lu.get("Region", "")
                last = _age(lu["LastUsedDate"])
                detail = last
                if svc and svc != "N/A":
                    detail += f"  via {svc}"
                    if reg and reg != "N/A":
                        detail += f" ({reg})"
            else:
                detail = "never"
        except Exception:
            detail = "unknown"

        created = k["CreateDate"].strftime("%Y-%m-%d")
        print(
            f"  {k['AccessKeyId']}  {k['Status']:<10}  "
            f"created {created}  last used: {detail}"
        )
    print()


# ── iam rotate-key ────────────────────────────────────────────────────────────

def _cmd_rotate_key(_args: list[str]) -> None:
    iam = _iam_client()
    try:
        user = iam.get_user()["User"]
        username = user["UserName"]
    except botocore.exceptions.ClientError as e:
        _handle_error(e)
        return

    existing = iam.list_access_keys(UserName=username).get("AccessKeyMetadata", [])

    if len(existing) >= 2:
        print(f"User '{username}' already has 2 access keys (AWS maximum).")
        print("Existing keys:")
        for k in existing:
            print(f"  {k['AccessKeyId']}  {k['Status']}  created {_age(k['CreateDate'])}")
        delete_id = input("\nKey ID to delete before creating new one (blank to abort): ").strip()
        if not delete_id:
            print("Aborted.")
            return
        if delete_id not in {k["AccessKeyId"] for k in existing}:
            print(f"Key '{delete_id}' not found.")
            return
        try:
            iam.delete_access_key(UserName=username, AccessKeyId=delete_id)
            print(f"Deleted {delete_id}.")
        except botocore.exceptions.ClientError as e:
            _handle_error(e)
            return

    try:
        new_key = iam.create_access_key(UserName=username)["AccessKey"]
    except botocore.exceptions.ClientError as e:
        _handle_error(e)
        return

    print(f"\nNew access key for '{username}':")
    print(f"  Access Key ID:     {new_key['AccessKeyId']}")
    print(f"  Secret Access Key: {new_key['SecretAccessKey']}")
    print("\n  ⚠  Save the secret key now — it cannot be retrieved again.")

    # Offer to delete the old key
    old_keys = [k for k in existing if k["AccessKeyId"] != new_key["AccessKeyId"]]
    if old_keys:
        old = old_keys[0]
        answer = input(
            f"\nDelete old key {old['AccessKeyId']} ({old['Status']}, "
            f"created {_age(old['CreateDate'])})? [y/N] "
        ).strip().lower()
        if answer == "y":
            iam.delete_access_key(UserName=username, AccessKeyId=old["AccessKeyId"])
            print(f"Deleted {old['AccessKeyId']}.")
    print()


# ── iam simulate ──────────────────────────────────────────────────────────────

def _cmd_simulate(args: list[str]) -> None:
    if len(args) < 2:
        print("Usage: iam simulate <principal-arn> <action> [resource]")
        print("  iam simulate arn:aws:iam::123456789:user/alice s3:PutObject arn:aws:s3:::my-bucket/*")
        return

    principal_arn = args[0]
    action = args[1]
    resource = args[2] if len(args) > 2 else "*"

    iam = _iam_client()
    try:
        resp = iam.simulate_principal_policy(
            PolicySourceArn=principal_arn,
            ActionNames=[action],
            ResourceArns=[resource],
        )
    except botocore.exceptions.ClientError as e:
        _handle_error(e)
        return

    for result in resp.get("EvaluationResults", []):
        decision = result["EvalDecision"]
        symbol = "✓" if decision == "allowed" else "✗"
        print(f"\n  {symbol}  {result['EvalActionName']}  on  {result['EvalResourceName']}")
        print(f"     Decision: {decision.upper()}")

        matched = result.get("MatchedStatements", [])
        if matched:
            print("     Matched by:")
            for s in matched:
                print(f"       - {s.get('SourcePolicyId', '?')}  [{s.get('SourcePolicyType', '')}]")

        missing = result.get("MissingContextValues", [])
        if missing:
            print(f"     Missing context values: {', '.join(missing)}")

        org_decision = result.get("OrganizationsDecisionDetail", {}).get("AllowedByOrganizations")
        if org_decision is False:
            print("     Blocked by: AWS Organizations SCP")

    print()


# ── iam who-can ───────────────────────────────────────────────────────────────

def _cmd_who_can(args: list[str]) -> None:
    if not args:
        print("Usage: iam who-can <action> [resource]")
        print("  iam who-can s3:PutObject arn:aws:s3:::my-bucket/*")
        print("  Note: checks all users and roles — slow on large accounts.")
        return

    action = args[0]
    resource = args[1] if len(args) > 1 else "*"

    iam = _iam_client()

    principals: list[tuple[str, str]] = []
    try:
        for page in iam.get_paginator("list_users").paginate():
            for u in page["Users"]:
                principals.append(("user", u["Arn"]))
        for page in iam.get_paginator("list_roles").paginate():
            for r in page["Roles"]:
                principals.append(("role", r["Arn"]))
    except botocore.exceptions.ClientError as e:
        _handle_error(e)
        return

    print(f"\nWho can '{action}' on '{resource}'?")
    print(f"Checking {len(principals)} principals...\n")

    allowed: list[tuple[str, str]] = []
    skipped = 0

    for kind, arn in principals:
        try:
            resp = iam.simulate_principal_policy(
                PolicySourceArn=arn,
                ActionNames=[action],
                ResourceArns=[resource],
            )
            decision = resp["EvaluationResults"][0]["EvalDecision"]
            if decision == "allowed":
                allowed.append((kind, arn))
        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            # Service-linked roles and some other ARNs can't be simulated
            if code in ("InvalidInput", "NoSuchEntity"):
                skipped += 1
            else:
                skipped += 1

    if allowed:
        print(f"  ALLOWED ({len(allowed)}):")
        for kind, arn in sorted(allowed, key=lambda x: (x[0], x[1])):
            print(f"    ✓ [{kind}]  {arn}")
    else:
        print("  No principals with explicit ALLOW found.")

    denied_count = len(principals) - len(allowed) - skipped
    print(f"\n  Checked: {len(principals)}  |  Allowed: {len(allowed)}  |  "
          f"Denied: {denied_count}  |  Skipped (unsimulatable): {skipped}")
    print()


# ── dispatch ──────────────────────────────────────────────────────────────────

_SUBCOMMAND_MAP = {
    "users": _cmd_users,
    "groups": _cmd_groups,
    "roles": _cmd_roles,
    "user": _cmd_user,
    "group": _cmd_group,
    "role": _cmd_role,
    "keys": _cmd_keys,
    "rotate-key": _cmd_rotate_key,
    "simulate": _cmd_simulate,
    "who-can": _cmd_who_can,
}


def cmd_iam(args: list[str]) -> None:
    if not args:
        _print_iam_help()
        return
    sub = args[0].lower()
    fn = _SUBCOMMAND_MAP.get(sub)
    if fn is None:
        print(f"Unknown iam subcommand '{sub}'. Run 'iam' for help.")
        return
    fn(args[1:])


def _print_iam_help() -> None:
    print("""
IAM commands:
  iam users [prefix]                  List IAM users
  iam groups [prefix]                 List IAM groups
  iam roles [prefix]                  List IAM roles
  iam user <name>                     Full detail: policies, groups, keys, MFA
  iam group <name>                    Members + policies
  iam role <name>                     Trust policy + attached policies
  iam keys [username]                 List access keys (defaults to current caller)
  iam rotate-key                      Create a new key for yourself, optionally delete old
  iam simulate <principal-arn> <action> [resource]
                                      Check if a principal is allowed an action
  iam who-can <action> [resource]     Find all users/roles allowed to perform an action
""")


def list_usernames() -> list[str]:
    """Return all IAM usernames — used by tab completion."""
    try:
        iam = _iam_client()
        names = []
        for page in iam.get_paginator("list_users").paginate():
            names.extend(u["UserName"] for u in page["Users"])
        return names
    except Exception:
        return []


def list_groupnames() -> list[str]:
    """Return all IAM group names — used by tab completion."""
    try:
        iam = _iam_client()
        names = []
        for page in iam.get_paginator("list_groups").paginate():
            names.extend(g["GroupName"] for g in page["Groups"])
        return names
    except Exception:
        return []


def list_rolenames() -> list[str]:
    """Return all IAM role names — used by tab completion."""
    try:
        iam = _iam_client()
        names = []
        for page in iam.get_paginator("list_roles").paginate():
            names.extend(r["RoleName"] for r in page["Roles"])
        return names
    except Exception:
        return []
