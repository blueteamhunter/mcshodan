Got it — we’ll lock the Lambda to only assume roles in two specific accounts (B and C) and ignore the rest. Here’s a safe approach that also tightens IAM.

What we’ll do

Add an env var ALLOWED_ACCOUNT_IDS (comma-separated list)

Update the Lambda code to only target those accounts (and skip organizations:list-accounts if provided)

Optionally tighten the Lambda IAM so it can only sts:AssumeRole into those two role ARNs

1) Updated Lambda (full file, ready to paste)

If ALLOWED_ACCOUNT_IDS is set, we do not call Organizations.

If it’s empty, we fall back to Organizations (old behavior).

Clear logs show which accounts are targeted.

# lambda_function.py
# Runtime: Python 3.11
#
# Required ENV VARS:
#   ORG_ROLE_NAME       = OrgRoute53ReadRole
#   REPORT_BUCKET       = org-dns-reports-123456789012
#   REPORT_PREFIX       = route53/monthly/
#   SNS_TOPIC_ARN       = arn:aws:sns:<region>:<acct>:route53-monthly-dns-report
# Optional:
#   PRESIGN_TTL_SEC     = 604800       # 7 days default
#   ALLOWED_ACCOUNT_IDS = 111111111111,222222222222  # only process these accounts; skip Organizations API

import os
import io
import csv
import time
import json
import logging
from typing import Dict, List, Tuple
from datetime import datetime, timezone

import boto3
import botocore

# ---------- Config ----------
ORG_ROLE_NAME     = os.environ["ORG_ROLE_NAME"]
REPORT_BUCKET     = os.environ["REPORT_BUCKET"]
REPORT_PREFIX     = os.environ.get("REPORT_PREFIX", "route53/monthly/")
SNS_TOPIC_ARN     = os.environ["SNS_TOPIC_ARN"]
PRESIGN_TTL_SEC   = int(os.environ.get("PRESIGN_TTL_SEC", "604800"))  # 7 days default
ALLOWED_ACCOUNTS  = [a.strip() for a in os.environ.get("ALLOWED_ACCOUNT_IDS", "").split(",") if a.strip()]

# AWS clients (create lazily to avoid needing Orgs if not used)
STS = boto3.client("sts")
S3  = boto3.client("s3")
SNS = boto3.client("sns")

# Logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------- Helpers ----------
def _normalize_prefix(prefix: str) -> str:
    return prefix if prefix.endswith("/") else prefix + "/"

def _backoff_call(fn, *args, **kwargs):
    """Exponential backoff wrapper for throttling-prone calls."""
    delay = 1.0
    for attempt in range(8):
        try:
            return fn(*args, **kwargs)
        except botocore.exceptions.ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("Throttling", "ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"):
                if attempt == 7:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            raise

def assume_r53_client(account_id: str):
    """Assume the cross-account Route53 read role and return a Route53 client."""
    resp = STS.assume_role(
        RoleArn=f"arn:aws:iam::{account_id}:role/{ORG_ROLE_NAME}",
        RoleSessionName=f"r53Export-{int(time.time())}"
    )
    c = resp["Credentials"]
    return boto3.client(
        "route53",
        aws_access_key_id=c["AccessKeyId"],
        aws_secret_access_key=c["SecretAccessKey"],
        aws_session_token=c["SessionToken"]
    )

def get_target_accounts() -> List[Dict]:
    """
    Returns a list of dicts [{Id:<acctId>, Name:<label>}, ...]
    If ALLOWED_ACCOUNT_IDS is set, only those accounts are used (Name=Id).
    Otherwise, falls back to Organizations list (ACTIVE accounts).
    """
    if ALLOWED_ACCOUNTS:
        logger.info("Using ALLOWED_ACCOUNT_IDS: %s", ",".join(ALLOWED_ACCOUNTS))
        return [{"Id": aid, "Name": aid} for aid in ALLOWED_ACCOUNTS]

    # Fall back to Organizations (requires organizations:ListAccounts)
    ORG = boto3.client("organizations")
    out = []
    token = None
    while True:
        kwargs = {}
        if token:
            kwargs["NextToken"] = token
        resp = _backoff_call(ORG.list_accounts, **kwargs)
        out.extend(a for a in resp["Accounts"] if a["Status"] == "ACTIVE")
        token = resp.get("NextToken")
        if not token:
            break
    return out

def list_all_hosted_zones(r53) -> List[Dict]:
    zones = []
    marker = None
    while True:
        kwargs = {}
        if marker:
            kwargs["Marker"] = marker
        resp = _backoff_call(r53.list_hosted_zones, **kwargs)
        zones.extend(resp.get("HostedZones", []))
        if resp.get("IsTruncated"):
            marker = resp.get("NextMarker")
        else:
            break
    return zones

def list_all_record_sets(r53, zone_id: str) -> List[Dict]:
    records = []
    start_name = None
    start_type = None
    while True:
        kwargs = {"HostedZoneId": zone_id, "MaxItems": "1000"}
        if start_name:
            kwargs["StartRecordName"] = start_name
        if start_type:
            kwargs["StartRecordType"] = start_type
        resp = _backoff_call(r53.list_resource_record_sets, **kwargs)
        rrs = resp.get("ResourceRecordSets", [])
        records.extend(rrs)
        if resp.get("IsTruncated"):
            start_name = resp.get("NextRecordName")
            start_type = resp.get("NextRecordType")
        else:
            break
    return records

def record_to_row(account_id: str, zone: Dict, record: Dict) -> Dict:
    values = ""
    if "ResourceRecords" in record:
        values = ";".join(rr["Value"] for rr in record["ResourceRecords"])
    elif "AliasTarget" in record:
        values = f"ALIAS->{record['AliasTarget'].get('DNSName')}"
    return {
        "AccountId": account_id,
        "ZoneId": zone["Id"].split("/")[-1],
        "ZoneName": zone["Name"],
        "PrivateZone": zone.get("Config", {}).get("PrivateZone", False),
        "RecordName": record.get("Name", ""),
        "Type": record.get("Type", ""),
        "TTL": record.get("TTL", ""),
        "Values": values
    }

def rows_to_csv_bytes(rows: List[Dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["AccountId", "ZoneId", "ZoneName", "PrivateZone", "RecordName", "Type", "TTL", "Values"]
    )
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")

def s3_put(key: str, body: bytes) -> None:
    _backoff_call(S3.put_object, Bucket=REPORT_BUCKET, Key=key, Body=body)

def s3_presign(key: str, expires: int = PRESIGN_TTL_SEC) -> str:
    return S3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": REPORT_BUCKET, "Key": key},
        ExpiresIn=expires
    )

def publish_sns(subject: str, message: str) -> None:
    SNS.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=message)

def collect_account_rows(account_id: str, account_name: str) -> Tuple[List[Dict], int, int]:
    """Return (rows, zone_count, record_count) for a single account."""
    r53 = assume_r53_client(account_id)
    zones = list_all_hosted_zones(r53)
    zc = len(zones)
    rc = 0
    rows: List[Dict] = []
    for z in zones:
        rrs = list_all_record_sets(r53, z["Id"])
        rc += len(rrs)
        rows.extend(record_to_row(account_id, z, r) for r in rrs)
    logger.info("Account %s (%s): zones=%d records=%d", account_name, account_id, zc, rc)
    return rows, zc, rc

# ---------- Handler ----------
def lambda_handler(event, context):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = _normalize_prefix(REPORT_PREFIX)

    # 1) Determine target accounts
    accounts = get_target_accounts()
    logger.info("Targeting %d account(s): %s", len(accounts), ",".join(a["Id"] for a in accounts))

    master_rows: List[Dict] = []
    summaries: List[Tuple[str, str, int, int]] = []

    # 2) Per-account export
    for acc in accounts:
        acc_id = acc["Id"]
        acc_name = acc.get("Name", acc_id)
        try:
            rows, zc, rc = collect_account_rows(acc_id, acc_name)

            # Write per-account CSV to S3
            acc_key = f"{prefix}{stamp}/route53_{acc_name}_{acc_id}.csv"
            s3_put(acc_key, rows_to_csv_bytes(rows))

            # Aggregate for master CSV + summary
            master_rows.extend(rows)
            summaries.append((acc_name, acc_id, zc, rc))
        except Exception as e:
            logger.warning("Account %s (%s) failed: %s", acc_name, acc_id, e)
            summaries.append((acc_name, acc_id, -1, -1))

    # 3) Master CSV with short key + pre-signed URL
    date_prefix = f"{prefix}{stamp}/"
    master_key  = f"{date_prefix}ALL.csv"
    if not master_key.strip():
        raise RuntimeError("master_key resolved empty; check REPORT_PREFIX and stamp")
    s3_put(master_key, rows_to_csv_bytes(master_rows))
    master_link = s3_presign(master_key)

    # 4) Minimal SNS message with angle-bracketed link (to reduce wrapping issues)
    lines = [
        f"Route 53 Monthly Export — {stamp}",
        "",
        "Summary (Account, Id, Zones, Records):"
    ]
    for name, aid, zc, rc in summaries:
        lines.append(f"- {name}, {aid}, {zc}, {rc}")
    lines += [
        "",
        "Master CSV link (valid for 7 days):",
        f"<{master_link}>",
        "",
        "If the link looks broken, copy EVERYTHING between the angle brackets on the line above."
    ]
    message = "\n".join(lines)

    subject = f"[Route53] Monthly DNS Export {stamp}"
    publish_sns(subject, message)

    result = {
        "accountsProcessed": len(accounts),
        "rowsInMaster": len(master_rows),
        "masterKey": master_key,
        "presignedUrlTTLSeconds": PRESIGN_TTL_SEC
    }
    logger.info("Done: %s", json.dumps(result))
    return result

2) Set the allowlist and redeploy (Ubuntu/WSL)

Replace with your two account IDs:

export ALLOWED_ACCOUNT_IDS="111111111111,222222222222"   # <--- B and C


Update the Lambda environment to include it:

aws lambda update-function-configuration \
  --function-name "$FUNC_NAME" \
  --environment "Variables={\
ORG_ROLE_NAME=$ORG_ROLE_NAME,\
REPORT_BUCKET=$BUCKET,\
REPORT_PREFIX=$REPORT_PREFIX,\
SNS_TOPIC_ARN=$SNS_TOPIC_ARN,\
PRESIGN_TTL_SEC=$PRESIGN_TTL_SEC,\
ALLOWED_ACCOUNT_IDS=$ALLOWED_ACCOUNT_IDS}" \
  --timeout 900 --memory-size 512 --region "$REGION"


Zip and push the new code:

rm -f function.zip
zip -r function.zip lambda_function.py
aws lambda update-function-code --function-name "$FUNC_NAME" --zip-file fileb://function.zip --region "$REGION"


Test:

aws lambda invoke --function-name "$FUNC_NAME" --payload '{}' --region "$REGION" out.json && cat out.json
aws logs tail "/aws/lambda/$FUNC_NAME" --follow --since 15m --region "$REGION"


You should see a log line like:

Targeting 2 account(s): 111111111111,222222222222

3) (Optional but recommended) Tighten IAM to only those two accounts

Update the Lambda role’s inline policy so sts:AssumeRole can target only B and C:

cat > only-two-accounts.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["organizations:ListAccounts"], "Resource": "*" },
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": [
        "arn:aws:iam::111111111111:role/$ORG_ROLE_NAME",
        "arn:aws:iam::222222222222:role/$ORG_ROLE_NAME"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject","s3:GetObject","s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::$BUCKET",
        "arn:aws:s3:::$BUCKET/*"
      ]
    },
    { "Effect": "Allow", "Action": ["sns:Publish"], "Resource": "$SNS_TOPIC_ARN" },
    { "Effect": "Allow", "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"], "Resource": "*" }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name route53-monthly-export-inline \
  --policy-document file://only-two-accounts.json


(You can remove the organizations:ListAccounts statement entirely if you’ll always use ALLOWED_ACCOUNT_IDS.)

✅ Result

Lambda only assumes roles in accounts B and C (allowlist driven)

Optional IAM hardening prevents assuming into any other account

Everything else (S3 write, SNS email with short presigned URL) stays the same

If you want to later switch to an OU allowlist instead (e.g., only accounts under /Workloads/Prod), I can give you a variant that uses list_accounts_for_parent(ParentId=ou-xxxx-yyyy) without a static ID list.
