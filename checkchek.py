awesome — let’s stand up the test Lambda from scratch in Account A, using CLI on your WSL Ubuntu. This version is read-only and doesn’t send email or use S3. It assumes roles into Accounts B & C, lists all hosted zones and all records, and writes one Excel per zone to /tmp. You’ll see a JSON summary on invoke + details in CloudWatch Logs.

0) Set your region & IDs (shell vars)
export AWS_REGION=us-east-1          # pick your region for Lambda
export ACCOUNT_A_ID=111111111111     # tooling account (Lambda lives here)
export ACCOUNT_B_ID=222222222222     # target
export ACCOUNT_C_ID=333333333333     # target

1) (Recap) Target roles in B & C (if not already done)

Create Route53ReadExport role in B and C:

Trust (trusts Account A’s Lambda role; you can fill this later once you know the role ARN)
For now you can temporarily trust Account A root (easier while bootstrapping), then tighten to the role ARN later:

{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::111111111111:root" },
      "Action": "sts:AssumeRole" }
  ]
}


Permissions (read-only Route53):

{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow",
      "Action": ["route53:ListHostedZones","route53:ListResourceRecordSets"],
      "Resource": "*" }
  ]
}


After you create the Lambda role (next step), tighten trust to the role ARN (least privilege). I show that change below.

2) Create the Lambda execution role (Account A)
2.1 Trust policy (Lambda service)

Save as trust-lambda.json:

{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "LambdaTrust", "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole" }
  ]
}


Create role:

aws iam create-role \
  --role-name r53-exporter-lambda-role \
  --assume-role-policy-document file://trust-lambda.json


Attach basic logs (managed policy):

aws iam attach-role-policy \
  --role-name r53-exporter-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

2.2 Inline permissions (allow AssumeRole into B & C)

Save as lambda-inline-perms.json (replace IDs if needed):

{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "AssumeTargets", "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": [
        "arn:aws:iam::222222222222:role/Route53ReadExport",
        "arn:aws:iam::333333333333:role/Route53ReadExport"
      ] }
  ]
}


Attach:

aws iam put-role-policy \
  --role-name r53-exporter-lambda-role \
  --policy-name r53-exporter-assume-targets \
  --policy-document file://lambda-inline-perms.json


Get the role ARN (you’ll need it to tighten B/C trust later):

aws iam get-role --role-name r53-exporter-lambda-role \
  --query 'Role.Arn' --output text


Example: arn:aws:iam::111111111111:role/r53-exporter-lambda-role

3) Attach the openpyxl layer

(You already built/published the layer in WSL earlier. If not, I can re-send those steps.)

Grab its LayerVersionArn, e.g.:

arn:aws:lambda:us-east-1:111111111111:layer:openpyxl-3_1_5:1

4) Create the function package

Create a working folder and drop in the test Lambda:

mkdir -p ~/lambda/route53-exporter-test && cd ~/lambda/route53-exporter-test


Create lambda_function.py with this read-only test code:

import os, time, datetime, logging, re
import boto3
from botocore.config import Config
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

log = logging.getLogger()
log.setLevel(logging.INFO)

ROUTE53_REGION = "us-east-1"
TMP_DIR = "/tmp"

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

def lambda_handler(event, context):
    role_arns = [a.strip() for a in _env("TARGET_ROLE_ARNS", required=True).split(",") if a.strip()]
    write_excel = _env("WRITE_EXCEL", "true").lower() == "true"
    max_paths = int(_env("MAX_PATHS_IN_OUTPUT", "25"))
    sample_records_per_zone = int(_env("SAMPLE_RECORDS_PER_ZONE", "3"))

    summary = {
        "run_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"),
        "accounts": [],
        "generated_files": [],
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

            path = None
            if write_excel:
                path = write_zone_workbook(account_id, zone_name or zone_id, zone_id, records)
                all_paths.append(path)
                log.info(f"[{account_id}] wrote {path} ({len(records)} records)")

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

    summary["totals"] = {"zones": total_zone_count, "records": total_record_count}
    summary["generated_files"] = all_paths[:max_paths]
    if len(all_paths) > max_paths:
        summary["generated_files_omitted"] = len(all_paths) - max_paths

    return summary


Zip it:

zip -j function.zip lambda_function.py

5) Create the Lambda function

Get your Lambda role ARN:

LAMBDA_ROLE_ARN=$(aws iam get-role --role-name r53-exporter-lambda-role \
  --query 'Role.Arn' --output text)
echo $LAMBDA_ROLE_ARN


Create the function:

aws lambda create-function \
  --function-name route53-exporter-test \
  --runtime python3.12 \
  --role "$LAMBDA_ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip \
  --region $AWS_REGION


Attach the openpyxl layer:

aws lambda update-function-configuration \
  --function-name route53-exporter-test \
  --layers arn:aws:lambda:$AWS_REGION:$ACCOUNT_A_ID:layer:openpyxl-3_1_5:1 \
  --region $AWS_REGION


Set environment variables:

aws lambda update-function-configuration \
  --function-name route53-exporter-test \
  --environment "Variables={\
TARGET_ROLE_ARNS=arn:aws:iam::$ACCOUNT_B_ID:role/Route53ReadExport,arn:aws:iam::$ACCOUNT_C_ID:role/Route53ReadExport,\
WRITE_EXCEL=true,MAX_PATHS_IN_OUTPUT=25,SAMPLE_RECORDS_PER_ZONE=3}" \
  --timeout 600 \
  --memory-size 1024 \
  --region $AWS_REGION


(If B/C trust requires ExternalId, add EXTERNAL_ID=your-id above.)

6) Tighten B/C trust to the role ARN (least privilege)

Now update B and C trust policies to only trust your role:

{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "TrustAccountARoleOnly", "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::111111111111:role/r53-exporter-lambda-role" },
      "Action": "sts:AssumeRole"
      /* , "Condition": { "StringEquals": { "sts:ExternalId": "YOUR_EXTERNAL_ID" } } */
    }
  ]
}

7) Test invoke & logs

Invoke:

aws lambda invoke \
  --function-name route53-exporter-test \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  out.json --region $AWS_REGION && cat out.json | jq


Tail logs:

aws logs tail "/aws/lambda/route53-exporter-test" --follow --region $AWS_REGION


You should see log lines like:

[222222222222] hosted zones: 7
[222222222222] wrote /tmp/route53-222222222222-example_com-20251007T...Z.xlsx (42 records)

That’s it

Once you’re happy with the output (counts, files written to /tmp), you can switch to the SES version to deliver the per-zone Excel files via email. If you want, I can also generate a one-shot script that runs every command above for you with your real IDs.
