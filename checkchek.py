Here’s a minimal Lambda to test the whole Route 53 crawl and one-Excel-per-zone export — no email, no S3. It assumes the cross-account roles, lists all zones and all records, writes .xlsx per zone to /tmp, and returns a concise summary you can see in the test result & CloudWatch Logs.

1) What this test Lambda does

Assumes roles into Accounts B & C (from TARGET_ROLE_ARNS).

For each hosted zone, fetches all record sets (paginated).

Writes one Excel workbook per zone to /tmp.

Returns a JSON summary: per-account zones, record counts, and a sample of the first few records and generated file paths.

No SES/SNS/S3 — pure functional test of logic & Excel generation.

2) Prereqs & config

IAM (unchanged from earlier):

Account A – Lambda execution role

Trust policy: lambda.amazonaws.com

Inline perms: CloudWatch Logs; sts:AssumeRole → arn:aws:iam::ACCOUNT_B_ID:role/Route53ReadExport, ...ACCOUNT_C_ID...

Accounts B & C – Route53ReadExport role

Trust: arn:aws:iam::ACCOUNT_A_ID:role/r53-exporter-lambda-role (optionally require ExternalId)

Perms: route53:ListHostedZones, route53:ListResourceRecordSets

Lambda settings

Runtime: Python 3.12

Memory: 512–1024 MB

Timeout: 5–10 min

Layer: openpyxl (build as before)

Environment variables:

TARGET_ROLE_ARNS = arn:aws:iam::ACCOUNT_B_ID:role/Route53ReadExport,arn:aws:iam::ACCOUNT_C_ID:role/Route53ReadExport

WRITE_EXCEL = true # set false to dry-run without writing files

MAX_PATHS_IN_OUTPUT = 25 # cap number of file paths returned

SAMPLE_RECORDS_PER_ZONE = 3 # number of sample records to return per zone in output

EXTERNAL_ID = (optional; only if B/C trust requires it)

3) Lambda code (paste as lambda_function.py)
import os, time, datetime, logging, re
import boto3
from botocore.config import Config
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

log = logging.getLogger()
log.setLevel(logging.INFO)

ROUTE53_REGION = "us-east-1"  # Route 53 is global; us-east-1 is fine for client
TMP_DIR = "/tmp"

# ---------- helpers ----------
def _env(name, default=None, required=False):
    v = os.environ.get(name, default)
    if required and (v is None or v == ""):
        raise RuntimeError(f"Missing required env var: {name}")
    return v

def assume_session(role_arn: str, session_name: str, duration=3600) -> boto3.Session:
    sts = boto3.client("sts")
    kwargs = {"RoleArn": role_arn, "RoleSessionName": session_name, "DurationSeconds": duration}
    external_id = os.environ.get("EXTERNAL_ID")
    if external_id:
        kwargs["ExternalId"] = external_id
    creds = sts.assume_role(**kwargs)["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )

def list_all_zones(r53_client):
    zones, marker = [], None
    while True:
        resp = r53_client.list_hosted_zones(Marker=marker) if marker else r53_client.list_hosted_zones()
        zones.extend(resp.get("HostedZones", []))
        if resp.get("IsTruncated"):
            marker = resp.get("NextMarker")
        else:
            break
    return zones

def list_all_records(r53_client, zone_id):
    recs, params = [], {"HostedZoneId": zone_id}
    while True:
        resp = r53_client.list_resource_record_sets(**params)
        recs.extend(resp.get("ResourceRecordSets", []))
        if resp.get("IsTruncated"):
            params["StartRecordName"] = resp["NextRecordName"]
            params["StartRecordType"] = resp["NextRecordType"]
            if "NextRecordIdentifier" in resp:
                params["StartRecordIdentifier"] = resp["NextRecordIdentifier"]
        else:
            break
    return recs

def sanitize_sheet_name(name: str) -> str:
    name = re.sub(r'[:\\/\?\*\[\]]', '-', name)
    return name[:31] if len(name) > 31 else name

def sanitize_filename(name: str, maxlen=120) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', name)[:maxlen]

def write_zone_workbook(account_id: str, zone_name: str, zone_id: str, records: list) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = sanitize_sheet_name(zone_name or zone_id)

    headers = [
        "ZoneName","ZoneId","RecordName","Type","TTL","Values",
        "AliasDNSName","AliasHostedZoneId","EvaluateTargetHealth",
        "SetIdentifier","Weight","Failover","Region","MultiValueAnswer"
    ]
    ws.append(headers)

    for rr in records:
        name = rr.get("Name","")
        rtype = rr.get("Type","")
        ttl = rr.get("TTL","")
        values = "\n".join([v.get("Value","") for v in rr.get("ResourceRecords", [])])
        alias = rr.get("AliasTarget", {})
        row = [
            zone_name, zone_id, name, rtype, ttl, values,
            alias.get("DNSName",""), alias.get("HostedZoneId",""), alias.get("EvaluateTargetHealth",""),
            rr.get("SetIdentifier",""), rr.get("Weight",""), rr.get("Failover",""),
            rr.get("Region",""), rr.get("MultiValueAnswer","")
        ]
        ws.append(row)

    # Autosize (bounded)
    for col_idx, _ in enumerate(ws.iter_cols(min_row=1, max_row=1), start=1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for cell in ws[col_letter]:
            val = str(cell.value) if cell.value is not None else ""
            if len(val) > max_len:
                max_len = len(val)
        ws.column_dimensions[col_letter].width = min(max_len + 2, 60)

    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_zone = sanitize_filename(zone_name.rstrip(".") if zone_name else zone_id)
    out_path = f"{TMP_DIR}/route53-{account_id}-{safe_zone}-{ts}.xlsx"
    wb.save(out_path)
    return out_path

# ---------- handler ----------
def lambda_handler(event, context):
    # env
    role_arns = [a.strip() for a in _env("TARGET_ROLE_ARNS", required=True).split(",") if a.strip()]
    write_excel = _env("WRITE_EXCEL", "true").lower() == "true"
    max_paths = int(_env("MAX_PATHS_IN_OUTPUT", "25"))
    sample_records_per_zone = int(_env("SAMPLE_RECORDS_PER_ZONE", "3"))

    summary = {
        "run_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"),
        "accounts": [],
        "generated_files": [],  # capped for response
    }

    total_zone_count = 0
    total_record_count = 0
    all_paths = []

    for role_arn in role_arns:
        account_id = role_arn.split(":")[4]
        log.info(f"[{account_id}] assuming role: {role_arn}")
        sess = assume_session(role_arn, session_name=f"r53-export-{int(time.time())}")
        r53 = sess.client("route53", region_name=ROUTE53_REGION,
                          config=Config(retries={"max_attempts": 10, "mode": "adaptive"}))

        zones = list_all_zones(r53)
        log.info(f"[{account_id}] hosted zones: {len(zones)}")

        acct_zone_count = 0
        acct_record_count = 0
        acct_detail = {"account_id": account_id, "zones": []}

        for z in zones:
            zone_id = z["Id"].split("/")[-1]
            zone_name = z.get("Name", "").rstrip(".")
            records = list_all_records(r53, zone_id)

            acct_zone_count += 1
            acct_record_count += len(records)

            # write workbook per zone (if enabled)
            path = None
            if write_excel:
                path = write_zone_workbook(account_id, zone_name or zone_id, zone_id, records)
                all_paths.append(path)
                log.info(f"[{account_id}] wrote {path} ({len(records)} records)")

            # sample a few records for quick inspection
            sample = []
            for rr in records[:sample_records_per_zone]:
                sample.append({
                    "Name": rr.get("Name",""),
                    "Type": rr.get("Type",""),
                    "TTL": rr.get("TTL",""),
                    "ValuesCount": len(rr.get("ResourceRecords", [])),
                    "Alias": bool(rr.get("AliasTarget"))
                })

            acct_detail["zones"].append({
                "zone_name": zone_name or zone_id,
                "zone_id": zone_id,
                "record_count": len(records),
                "sample_records": sample,
                "file_path": path
            })

        total_zone_count += acct_zone_count
        total_record_count += acct_record_count
        acct_detail["zone_count"] = acct_zone_count
        acct_detail["total_records"] = acct_record_count
        summary["accounts"].append(acct_detail)

    # Cap the file path list in the response
    summary["totals"] = {"zones": total_zone_count, "records": total_record_count}
    summary["generated_files"] = all_paths[:max_paths]
    if len(all_paths) > max_paths:
        summary["generated_files_omitted"] = len(all_paths) - max_paths

    return summary

4) How to test

A) Quick console test

In Lambda → Test → create a test event (any JSON, e.g. {}).

Run.

Check:

Return value (JSON) shows per-account totals, zone samples, and a list of file paths written under /tmp.

CloudWatch Logs show lines like:
wrote /tmp/route53-123456789012-example_com-20251007T150012Z.xlsx (42 records)

B) AWS CLI test (from your machine)

aws lambda invoke \
  --function-name route53-exporter-test \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  out.json && cat out.json | jq


Note: /tmp is ephemeral inside the Lambda container and not directly retrievable. This test is meant to verify logic, pagination, counts, and file creation. When you’re satisfied, re-enable your SES flow (or add S3) to actually receive the files.

5) Common tweaks

Set WRITE_EXCEL=false to validate speed and pagination first (no files written).

Increase timeout if you have many zones/records.

If B/C trust uses ExternalId, set EXTERNAL_ID env var — the code already supports it.
