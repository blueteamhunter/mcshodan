1) What you’ll build

Account A (tooling): Lambda + EventBridge + SES (email).

Accounts B & C (targets): one read-only Route 53 role each, assumed by the Lambda in A.

Behavior: For each target account, list all hosted zones and for each zone list all records → write one .xlsx per zone → email via SES. If too big for a single email, the function splits into multiple emails (or zips results first, still as attachments).

2) SES setup (Account A)

Choose region (e.g., us-east-1).

Verify sender domain or From address (configure SPF/DKIM).

If SES is in sandbox, either request production or verify all recipients.

3) IAM — Account A (Lambda execution role)
Trust policy (Account A → Lambda service)
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "LambdaTrust", "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole" }
  ]
}

Inline permissions policy (what Lambda can do)
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "Logs", "Effect": "Allow",
      "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],
      "Resource": "arn:aws:logs:*:*:*" },

    { "Sid": "AssumeTargets", "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": [
        "arn:aws:iam::ACCOUNT_B_ID:role/Route53ReadExport",
        "arn:aws:iam::ACCOUNT_C_ID:role/Route53ReadExport"
      ] },

    { "Sid": "EmailWithSES", "Effect": "Allow",
      "Action": ["ses:SendRawEmail"],
      "Resource": "*" }
  ]
}


(Optionally attach the managed AWSLambdaBasicExecutionRole instead of “Logs”.)

4) IAM — Accounts B & C (Route53 read-only role)

Create Route53ReadExport in both B and C.

Trust policy (trust the role in Account A)
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "TrustAccountARoleOnly", "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::ACCOUNT_A_ID:role/r53-exporter-lambda-role" },
      "Action": "sts:AssumeRole"
      /* , "Condition": { "StringEquals": { "sts:ExternalId": "YOUR_EXTERNAL_ID" } } */
    }
  ]
}

Inline permissions policy (Route53 read)
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "Route53ReadOnly", "Effect": "Allow",
      "Action": ["route53:ListHostedZones","route53:ListResourceRecordSets"],
      "Resource": "*" }
  ]
}


(If you enable ExternalId in trust above, set env EXTERNAL_ID in Lambda and pass it to AssumeRole—code snippet included below.)

5) Lambda layer (openpyxl)

Build the openpyxl layer on Linux (same arch/runtime as Lambda):

mkdir -p layer/python
pip install --upgrade pip
pip install --target layer/python openpyxl==3.1.5
cd layer && zip -r ../openpyxl-layer.zip python && cd ..


Create a Lambda Layer from openpyxl-layer.zip.

6) Lambda configuration

Runtime: Python 3.12

Memory: 512–1024 MB

Timeout: 5–10 min (increase if many zones/records)

Layers: attach the openpyxl layer

Environment variables (SES-only):

TARGET_ROLE_ARNS = arn:aws:iam::ACCOUNT_B_ID:role/Route53ReadExport,arn:aws:iam::ACCOUNT_C_ID:role/Route53ReadExport

SES_REGION = us-east-1

FROM_ADDRESS = ops@yourdomain.com

TO_ADDRESSES = you@yourdomain.com,security@yourdomain.com

SIZE_LIMIT_MB = 7 ← per-email raw size budget (safe headroom under SES ~10MB)

MAX_ATTACHMENTS = 10 ← per-email attachment count cap

ZIP_STRATEGY = per_account ← none | per_account | all

EXTERNAL_ID = (optional; set only if your B/C trust requires it)

7) Lambda code (SES-only; one Excel per zone; no S3; auto-chunk emails)
import os, io, zipfile, time, datetime, logging, re
import boto3
from botocore.config import Config
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

log = logging.getLogger()
log.setLevel(logging.INFO)

ROUTE53_REGION = "us-east-1"  # Route 53 is global; us-east-1 is fine for boto3
TMP_DIR = "/tmp"
B64_OVERHEAD = 1.37  # rough multiplier for base64 inflation of attachments

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

def make_workbook_for_zone(account_id: str, zone_name: str, zone_id: str, records: list) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = sanitize_sheet_name(zone_name or zone_id)
    headers = ["ZoneName","ZoneId","RecordName","Type","TTL","Values",
               "AliasDNSName","AliasHostedZoneId","EvaluateTargetHealth",
               "SetIdentifier","Weight","Failover","Region","MultiValueAnswer"]
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
            max_len = max(max_len, len(val))
        ws.column_dimensions[col_letter].width = min(max_len + 2, 60)

    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_zone = sanitize_filename(zone_name.rstrip(".") if zone_name else zone_id)
    path = f"{TMP_DIR}/route53-{account_id}-{safe_zone}-{ts}.xlsx"
    wb.save(path)
    return path

def zip_files(filepaths, zip_name=None):
    if not zip_name:
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        zip_name = f"{TMP_DIR}/route53-exports-{ts}.zip"
    with zipfile.ZipFile(zip_name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fp in filepaths:
            zf.write(fp, arcname=os.path.basename(fp))
    return zip_name

def size_mb(path): return os.path.getsize(path) / (1024*1024)

def send_email_with_attachments(from_addr, to_addrs, subject, body_text, attachments):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-Id"] = make_msgid()
    msg.set_content(body_text)

    for att in attachments:
        maintype, subtype = att["mime"].split("/", 1)
        msg.add_attachment(att["content"], maintype=maintype, subtype=subtype, filename=att["filename"])

    ses = boto3.client("ses", region_name=os.environ["SES_REGION"])
    ses.send_raw_email(Source=from_addr, Destinations=to_addrs, RawMessage={"Data": msg.as_bytes()})

def chunk_and_send_emails(from_addr, to_addrs, base_subject, base_body_lines, paths, size_limit_mb, max_attachments):
    """
    Splits attachments across multiple emails to honor per-email size and count caps.
    Uses a greedy pack by file size (with base64 overhead).
    """
    # Pre-load sizes with base64 overhead
    items = []
    for p in paths:
        raw_mb = size_mb(p)
        est_mb = raw_mb * B64_OVERHEAD
        items.append((p, raw_mb, est_mb))

    batches = []
    cur, cur_mb = [], 0.0
    for p, raw_mb, est_mb in items:
        # if single file exceeds cap, we can't send it (suggest zip strategy)
        if est_mb > size_limit_mb:
            raise RuntimeError(f"Single attachment {os.path.basename(p)} ~{est_mb:.2f}MB exceeds SIZE_LIMIT_MB={size_limit_mb} (try ZIP_STRATEGY).")
        if len(cur) >= max_attachments or (cur_mb + est_mb) > size_limit_mb:
            if cur:
                batches.append(cur)
            cur, cur_mb = [], 0.0
        cur.append((p, est_mb))
        cur_mb += est_mb
    if cur:
        batches.append(cur)

    total = len(batches)
    for idx, batch in enumerate(batches, start=1):
        attachments = []
        names = []
        for p, est_mb in batch:
            with open(p, "rb") as f:
                data = f.read()
            mime = "application/zip" if p.endswith(".zip") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            attachments.append({"filename": os.path.basename(p), "content": data, "mime": mime})
            names.append(os.path.basename(p))
        subject = base_subject if total == 1 else f"{base_subject} (part {idx}/{total})"
        body_text = "\n".join(base_body_lines + ["", "Included attachments:", *[f"- {n}" for n in names]])
        send_email_with_attachments(from_addr, to_addrs, subject, body_text, attachments)

def lambda_handler(event, context):
    # Env
    target_role_arns = [a.strip() for a in _env("TARGET_ROLE_ARNS", required=True).split(",") if a.strip()]
    from_addr = _env("FROM_ADDRESS", required=True)
    to_addrs = [a.strip() for a in _env("TO_ADDRESSES", required=True).split(",") if a.strip()]
    size_limit_mb = float(_env("SIZE_LIMIT_MB", "7"))
    max_attachments = int(_env("MAX_ATTACHMENTS", "10"))
    zip_strategy = _env("ZIP_STRATEGY", "per_account").lower()  # none | per_account | all

    # Gather per-zone xlsx files
    per_zone_files = []
    files_by_account = {}

    for role_arn in target_role_arns:
        account_id = role_arn.split(":")[4]
        files_by_account.setdefault(account_id, [])
        log.info(f"Processing account {account_id}")
        sess = assume_session(role_arn, session_name=f"r53-export-{int(time.time())}")
        r53 = sess.client("route53", region_name=ROUTE53_REGION, config=Config(retries={"max_attempts": 10, "mode": "adaptive"}))
        zones = list_all_zones(r53)
        for z in zones:
            zone_id = z["Id"].split("/")[-1]
            zone_name = z.get("Name", "").rstrip(".")
            records = list_all_records(r53, zone_id)
            xlsx = make_workbook_for_zone(account_id, zone_name or zone_id, zone_id, records)
            per_zone_files.append(xlsx)
            files_by_account[account_id].append(xlsx)

    # Optionally zip (still attached via email; no S3)
    attach_paths = []
    if zip_strategy == "none":
        attach_paths = per_zone_files
    elif zip_strategy == "per_account":
        for acct, paths in files_by_account.items():
            if not paths: continue
            ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            z = zip_files(paths, zip_name=f"{TMP_DIR}/route53-exports-{acct}-{ts}.zip")
            attach_paths.append(z)
    elif zip_strategy == "all":
        z = zip_files(per_zone_files)
        attach_paths.append(z)
    else:
        raise RuntimeError(f"Unknown ZIP_STRATEGY: {zip_strategy}")

    # Email (chunk as needed)
    subject = f"Route 53 DNS Export – {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')} UTC"
    body_lines = [
        "Hello,",
        "",
        "Exports are attached.",
        ("One Excel file per hosted zone" if zip_strategy == "none" else
         "ZIP attached (contains per-zone Excel files)"),
        "",
        f"Note: Emails are split when exceeding ~{size_limit_mb}MB or {max_attachments} attachments."
    ]
    chunk_and_send_emails(from_addr, to_addrs, subject, body_lines, attach_paths, size_limit_mb, max_attachments)

    return {"ok": True, "files": [os.path.basename(p) for p in attach_paths], "zip_strategy": zip_strategy}


Notes

No S3 anywhere.

If a single file exceeds the SIZE_LIMIT_MB (after base64 overhead), the function raises an error with guidance to switch ZIP_STRATEGY (e.g., all or per_account) or increase the limit (staying under SES’s ~10MB raw cap).

Default ZIP_STRATEGY=per_account keeps the number of attachments low and compresses Excel files.

8) EventBridge schedule (São Paulo → UTC)

To run monthly on the 1st at 09:00 America/Sao_Paulo (UTC-3):

cron(0 12 1 * ? *)


Target: the Lambda function.

9) Validation checklist

 SES From verified and production access (or recipients verified).

 Account A Lambda role: trusts lambda.amazonaws.com, has logs, ses:SendRawEmail, and sts:AssumeRole to B & C.

 Accounts B & C: role trusts Account A Lambda role and allows Route53 read.

 Layer openpyxl attached; runtime Python 3.12.

 Env vars set (Section 6).

 Test invoke: Emails arrive with one .xlsx per zone (or zips), possibly split into multiple parts if large.
