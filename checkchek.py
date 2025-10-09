Awesome — let’s take your working test Lambda and turn it into a production job that:

writes the Route53 CSVs to a private S3 bucket,

generates time-limited pre-signed URLs,

and sends a short email via SNS containing those links (no SES).

Below is a clean, practical rollout plan you can follow end-to-end. I’ll give you the minimal code changes from your test Lambda plus the AWS steps to deploy and schedule it.

0) What you already have

A Python Lambda that enumerates Org accounts, assumes a read role, exports Route 53 zones/records, and wrote output locally (when you ran it on your terminal). Great!

We’ll adapt it to:

upload CSVs to S3,

pre-sign the “master” CSV (and optionally per-account CSVs),

publish a short message to SNS with those links.

1) Create the S3 reports bucket (private)

Pick a bucket name, e.g. org-dns-reports-<youracctid>.

aws s3api create-bucket --bucket org-dns-reports-123456789012 --region us-east-1
aws s3api put-bucket-versioning --bucket org-dns-reports-123456789012 --versioning-configuration Status=Enabled
# (optional) default encryption
aws s3api put-bucket-encryption --bucket org-dns-reports-123456789012 --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'


Keep Block Public Access = ON (default). We won’t make anything public; we’ll use pre-signed URLs.

2) Create an SNS topic and add email subscribers
aws sns create-topic --name route53-monthly-dns-report
# capture the TopicArn from the output into $TOPIC


Subscribe recipients (each must confirm the email they receive from SNS):

aws sns subscribe --topic-arn $TOPIC --protocol email --notification-endpoint it-team@yourco.com
aws sns subscribe --topic-arn $TOPIC --protocol email --notification-endpoint secops@yourco.com

Lock the topic to your Lambda role (only your Lambda may publish)

When you create the Lambda role in the next step, update the topic access policy like:

{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowLambdaToPublish",
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::<AUDIT_ACCOUNT_ID>:role/<LambdaRoleName>" },
    "Action": "SNS:Publish",
    "Resource": "arn:aws:sns:<REGION>:<AUDIT_ACCOUNT_ID>:route53-monthly-dns-report"
  }]
}


You can set this in Console → SNS → Topic → Access policy, or via set-topic-attributes.

3) Create the Lambda execution IAM role (audit account)

This role needs:

List Org accounts

Assume the member-account read role

Put/Get/List on your reports bucket (optionally only a prefix)

Publish to SNS

Trust policy (Lambda service)
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}

Permissions policy (tighten ARNs for prod)
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["organizations:ListAccounts"], "Resource": "*" },
    { "Effect": "Allow", "Action": ["sts:AssumeRole"], "Resource": "arn:aws:iam::*:role/OrgRoute53ReadRole" },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject","s3:GetObject","s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::org-dns-reports-123456789012",
        "arn:aws:s3:::org-dns-reports-123456789012/*"
      ]
    },
    { "Effect": "Allow", "Action": ["sns:Publish"], "Resource": "arn:aws:sns:<REGION>:<AUDIT_ACCOUNT_ID>:route53-monthly-dns-report" },
    { "Effect": "Allow", "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"], "Resource": "*" }
  ]
}


(Replace bucket name, account IDs, and region.)

4) Minimal code changes (Lambda) to use S3 + SNS

Below is a drop-in pattern for your Lambda to:

upload CSVs to S3,

create pre-signed link(s),

publish to SNS (no SES).

You only need to adapt the parts where your test code wrote files locally or printed output.

import boto3, os, io, csv, time
from datetime import datetime, timezone

ORG_ROLE_NAME = os.environ["ORG_ROLE_NAME"]                 # e.g., OrgRoute53ReadRole
REPORT_BUCKET = os.environ["REPORT_BUCKET"]                 # e.g., org-dns-reports-123456789012
REPORT_PREFIX = os.environ.get("REPORT_PREFIX", "route53/monthly/")
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]                 # arn:aws:sns:region:acct:route53-monthly-dns-report

ORG = boto3.client("organizations")
STS = boto3.client("sts")
S3  = boto3.client("s3")
SNS = boto3.client("sns")

def assume_role(account_id: str):
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

def rows_to_csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["AccountId","ZoneId","ZoneName","PrivateZone","RecordName","Type","TTL","Values"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")

def put_s3(key: str, body: bytes):
    S3.put_object(Bucket=REPORT_BUCKET, Key=key, Body=body)

def presign(key: str, seconds=7*24*3600) -> str:
    return S3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": REPORT_BUCKET, "Key": key},
        ExpiresIn=seconds
    )

def publish_sns(subject: str, message: str):
    SNS.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=message)

def lambda_handler(event, context):
    # 1) enumerate accounts
    accounts = []
    nt = None
    while True:
        kwargs = {}
        if nt: kwargs["NextToken"] = nt
        resp = ORG.list_accounts(**kwargs)
        accounts.extend(a for a in resp["Accounts"] if a["Status"] == "ACTIVE")
        nt = resp.get("NextToken")
        if not nt: break

    # 2) collect Route53 data and write per-account CSV to S3
    master_rows = []
    summaries = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for acc in accounts:
        acc_id, acc_name = acc["Id"], acc["Name"]
        try:
            r53 = assume_role(acc_id)
            # list zones
            zones, marker = [], None
            while True:
                kwargs = {}
                if marker: kwargs["Marker"] = marker
                z = r53.list_hosted_zones(**kwargs)
                zones.extend(z.get("HostedZones", []))
                if z.get("IsTruncated"):
                    marker = z.get("NextMarker")
                else:
                    break

            # list records per zone
            rows = []
            rec_total = 0
            for z in zones:
                zone_id = z["Id"].split("/")[-1]
                start_name = start_type = None
                while True:
                    rr_kwargs = {"HostedZoneId": z["Id"], "MaxItems": "1000"}
                    if start_name: rr_kwargs["StartRecordName"] = start_name
                    if start_type: rr_kwargs["StartRecordType"] = start_type
                    rr = r53.list_resource_record_sets(**rr_kwargs)
                    rrs = rr.get("ResourceRecordSets", [])
                    rec_total += len(rrs)
                    for r in rrs:
                        values = ""
                        if "ResourceRecords" in r:
                            values = ";".join(v["Value"] for v in r["ResourceRecords"])
                        elif "AliasTarget" in r:
                            values = f"ALIAS->{r['AliasTarget'].get('DNSName')}"
                        rows.append({
                            "AccountId": acc_id,
                            "ZoneId": zone_id,
                            "ZoneName": z["Name"],
                            "PrivateZone": z.get("Config", {}).get("PrivateZone", False),
                            "RecordName": r.get("Name",""),
                            "Type": r.get("Type",""),
                            "TTL": r.get("TTL",""),
                            "Values": values
                        })
                    if rr.get("IsTruncated"):
                        start_name = rr.get("NextRecordName")
                        start_type = rr.get("NextRecordType")
                    else:
                        break

            # write per-account csv to S3
            csv_bytes = rows_to_csv_bytes(rows)
            acc_key = f"{REPORT_PREFIX}{stamp}/route53_{acc_name}_{acc_id}.csv"
            put_s3(acc_key, csv_bytes)

            # aggregate
            master_rows.extend(rows)
            summaries.append((acc_name, acc_id, len(zones), rec_total))

        except Exception as e:
            summaries.append((acc_name, acc_id, -1, -1))
            print(f"[WARN] {acc_name} ({acc_id}) failed: {e}")

    # 3) master CSV in S3 + pre-signed URL
    master_key = f"{REPORT_PREFIX}{stamp}/route53_ALL_{stamp}.csv"
    put_s3(master_key, rows_to_csv_bytes(master_rows))
    master_link = presign(master_key)  # expires in 7 days

    # 4) publish to SNS (short message + link)
    lines = [f"Route 53 Monthly Export — {stamp}", ""]
    lines.append("AccountName, AccountId, Zones, Records")
    for n, i, zc, rc in summaries:
        lines.append(f"{n}, {i}, {zc}, {rc}")
    lines.append("")
    lines.append("Master CSV (expires in 7 days):")
    lines.append(master_link)

    publish_sns(subject=f"[Route53] Monthly DNS Export {stamp}", message="\n".join(lines))
    return {"accountsProcessed": len(accounts), "masterKey": master_key}

Environment variables for the Lambda

ORG_ROLE_NAME=OrgRoute53ReadRole

REPORT_BUCKET=org-dns-reports-123456789012

REPORT_PREFIX=route53/monthly/

SNS_TOPIC_ARN=arn:aws:sns:<REGION>:<AUDIT_ACCOUNT_ID>:route53-monthly-dns-report

5) Package & deploy the Lambda

If your Lambda only uses boto3/botocore (already available in AWS Lambda), you can deploy the single .py file:

zip function.zip lambda_function.py
aws lambda create-function \
  --function-name route53-monthly-export \
  --zip-file fileb://function.zip \
  --handler lambda_function.lambda_handler \
  --runtime python3.11 \
  --role arn:aws:iam::<AUDIT_ACCOUNT_ID>:role/<LambdaRoleName> \
  --environment "Variables={ORG_ROLE_NAME=OrgRoute53ReadRole,REPORT_BUCKET=org-dns-reports-123456789012,REPORT_PREFIX=route53/monthly/,SNS_TOPIC_ARN=arn:aws:sns:<REGION>:<AUDIT_ACCOUNT_ID>:route53-monthly-dns-report}"


(Use update-function-code for future edits.)

6) Test

In Lambda console, Test with {}.

Watch CloudWatch Logs for summary lines and any warnings.

SNS subscribers should receive an email with the pre-signed URL.

Try the link — it should download the CSV even though the bucket is private.

7) Schedule monthly (EventBridge)
aws events put-rule --name Route53MonthlyExport --schedule-expression "cron(0 8 1 * ? *)"
aws events put-targets --rule Route53MonthlyExport --targets "Id"="1","Arn"="arn:aws:lambda:<REGION>:<AUDIT_ACCOUNT_ID>:function:route53-monthly-export"
aws lambda add-permission --function-name route53-monthly-export --statement-id evt-allow --action lambda:InvokeFunction --principal events.amazonaws.com --source-arn arn:aws:events:<REGION>:<AUDIT_ACCOUNT_ID>:rule/Route53MonthlyExport

Security & Ops checklist

S3 private (Block Public Access ON), SSE enabled.

Lambda role: least privilege (limit S3 to the reports bucket/prefix).

SNS topic policy only allows your Lambda to publish.

CloudWatch alarm on Lambda errors.

S3 lifecycle to expire old reports after N months.

If you want, I can turn this into a Terraform or CloudFormation package so you can deploy in one shot (IAM role, topic + policy, bucket, Lambda, EventBridge).
