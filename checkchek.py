CLI from PowerShell. I’ll assume:

You’ll run this in your audit/central account.

The cross-account role OrgRoute53ReadRole already exists in each member account (as we designed earlier) with Route53 read permissions.

You’re not using SES (we’ll use SNS email + S3 pre-signed link).

Region: replace us-east-1 with yours where needed.

0) Prepare local files

Save your Lambda code as lambda_function.py in a clean folder (only this file).

# In the folder containing lambda_function.py
Compress-Archive -Path .\lambda_function.py -DestinationPath .\function.zip -Force

1) Create a private S3 bucket for reports (one-time)
$Bucket="org-dns-reports-<ACCOUNT_ID>"  # pick a unique name
$Region="us-east-1"

aws s3api create-bucket --bucket $Bucket --region $Region `
  --create-bucket-configuration LocationConstraint=$Region

# Versioning (optional but recommended)
aws s3api put-bucket-versioning --bucket $Bucket --versioning-configuration Status=Enabled

# Default encryption at rest (SSE-S3)
aws s3api put-bucket-encryption --bucket $Bucket `
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'


Make sure Block Public Access is ON (default). We won’t open this bucket.

2) Create SNS topic + subscribe recipients (one-time)
$TopicArn = (aws sns create-topic --name route53-monthly-dns-report --region $Region `
  --query TopicArn --output text)

# Add email subscribers (each will get a confirmation email)
aws sns subscribe --topic-arn $TopicArn --protocol email --notification-endpoint it-team@yourco.com --region $Region
aws sns subscribe --topic-arn $TopicArn --protocol email --notification-endpoint secops@yourco.com --region $Region


Leave the topic policy default for now; we’ll allow the Lambda to publish in the Lambda role policy.

3) Create the Lambda execution role (one-time)
3a) Trust policy (Lambda service)
$Trust = @"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
"@
$RoleName="route53-monthly-export-role"

aws iam create-role --role-name $RoleName --assume-role-policy-document "$Trust"

3b) Permissions policy (least privilege)

Replace bucket name and region; keep the OrgRoute53ReadRole name (or change to yours).

$PolicyDoc = @"
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["organizations:ListAccounts"], "Resource": "*" },
    { "Effect": "Allow", "Action": ["sts:AssumeRole"], "Resource": "arn:aws:iam::*:role/OrgRoute53ReadRole" },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject","s3:GetObject","s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::$Bucket",
        "arn:aws:s3:::$Bucket/*"
      ]
    },
    { "Effect": "Allow", "Action": ["sns:Publish"], "Resource": "$TopicArn" },
    { "Effect": "Allow", "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"], "Resource": "*" }
  ]
}
"@

aws iam put-role-policy --role-name $RoleName --policy-name route53-monthly-export-inline --policy-document "$PolicyDoc"

4) Create the Lambda function
$FuncName="route53-monthly-export"
$OrgRoleName="OrgRoute53ReadRole"               # role in member accounts
$ReportPrefix="route53/monthly/"

aws lambda create-function `
  --function-name $FuncName `
  --zip-file fileb://function.zip `
  --handler lambda_function.lambda_handler `
  --runtime python3.11 `
  --role arn:aws:iam::<ACCOUNT_ID>:role/$RoleName `
  --environment "Variables={ORG_ROLE_NAME=$OrgRoleName,REPORT_BUCKET=$Bucket,REPORT_PREFIX=$ReportPrefix,SNS_TOPIC_ARN=$TopicArn,PRESIGN_TTL_SEC=604800}" `
  --timeout 900 `
  --memory-size 512 `
  --region $Region


timeout 900s gives headroom for many accounts/records. Adjust memory if needed.

Updating later?

Compress-Archive -Path .\lambda_function.py -DestinationPath .\function.zip -Force
aws lambda update-function-code --function-name $FuncName --zip-file fileb://function.zip --region $Region

5) Test the function (manual)
aws lambda invoke --function-name $FuncName --payload "{}" out.json --region $Region
Get-Content .\out.json


Check CloudWatch Logs for the Lambda for warnings/errors:

Missing role in a member account

Throttling

AccessDenied on S3/SNS/Organizations

The SNS subscribers should receive an email with:

Per-account summary

Pre-signed URL to the master CSV (valid for 7 days by default)

Try the link; it should download even with a private bucket.

6) Schedule it monthly (EventBridge)

Run on 1st of the month @ 08:00 UTC:

$RuleName="Route53MonthlyExport"
aws events put-rule --name $RuleName --schedule-expression "cron(0 8 1 * ? *)" --region $Region

aws events put-targets --rule $RuleName --targets "Id"="1","Arn"="arn:aws:lambda:$Region:<ACCOUNT_ID>:function:$FuncName"

aws lambda add-permission `
  --function-name $FuncName `
  --statement-id evt-allow `
  --action lambda:InvokeFunction `
  --principal events.amazonaws.com `
  --source-arn arn:aws:events:$Region:<ACCOUNT_ID>:rule/$RuleName `
  --region $Region

7) Security checklist (important)

S3

Block Public Access = ON

SSE-S3 (or SSE-KMS) enabled

OPTIONAL: Restrict Lambda IAM to the prefix only ("arn:aws:s3:::$Bucket/$ReportPrefix*")

OrgRole in member accounts

route53:ListHostedZones, route53:ListResourceRecordSets only

Trusts your audit account role to assume

SNS

Only your Lambda role needs sns:Publish on the topic

Subscribers are the approved email list (confirmations completed)

Monitoring

Add a CloudWatch Alarm on the Lambda error metric

Consider a DLQ (SQS) for failed async invocations if you trigger via EventBridge with retry

8) Troubleshooting quick hits

SNS emails not arriving

Ensure subscribers confirmed.

If your AWS account is in GovCloud or has email filtering, check that no-reply@sns.amazonaws.com is allowed.

AccessDenied on S3 presigned link

Make sure the object exists (check S3 console) and URL is not expired.

The presign uses Lambda’s credentials to produce a link; the bucket itself stays private.

AccessDenied assuming member role

Confirm the member role name equals $OrgRoleName and its trust policy allows arn:aws:iam::<AUDIT_ACCOUNT_ID>:root or your Lambda role to assume.

Large org / many records

Increase memory (faster network/CPU) and timeout.

You can shard by OU or paginate accounts if needed.
