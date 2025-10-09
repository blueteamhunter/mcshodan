0) Set your variables (edit these!)
export REGION="us-east-1"
export ACCOUNT_ID="<YOUR_AUDIT_ACCOUNT_ID>"
export BUCKET="org-dns-reports-$ACCOUNT_ID"   # must be globally unique
export TOPIC_NAME="route53-monthly-dns-report"
export ROLE_NAME="route53-monthly-export-role"
export FUNC_NAME="route53-monthly-export"
export ORG_ROLE_NAME="OrgRoute53ReadRole"     # the cross-account role name in member accounts
export REPORT_PREFIX="route53/monthly/"
export PRESIGN_TTL_SEC="604800"               # 7 days

1) Zip your Lambda

In a clean folder where lambda_function.py is located:

zip -r function.zip lambda_function.py

2) Create a private S3 bucket for reports (one-time)
aws s3api create-bucket \
  --bucket "$BUCKET" \
  --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION"

aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
  }'
# Keep Block Public Access = ON (default)

3) Create an SNS topic and subscribe recipients (one-time)
TOPIC_ARN=$(aws sns create-topic --name "$TOPIC_NAME" --region "$REGION" --query TopicArn --output text)

# Add recipients (each will get a confirmation email they must approve)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint it-team@yourco.com --region "$REGION"
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint secops@yourco.com --region "$REGION"


(You can restrict the topic’s access via policy later if you want only your Lambda to publish; the Lambda role policy below already limits who can publish.)

4) Create the Lambda execution role (one-time)
4a) Trust policy (Lambda service)
cat > trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document file://trust-policy.json

4b) Inline permissions (least privilege)
cat > perm-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["organizations:ListAccounts"], "Resource": "*" },
    { "Effect": "Allow", "Action": ["sts:AssumeRole"], "Resource": "arn:aws:iam::*:role/$ORG_ROLE_NAME" },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject","s3:GetObject","s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::$BUCKET",
        "arn:aws:s3:::$BUCKET/*"
      ]
    },
    { "Effect": "Allow", "Action": ["sns:Publish"], "Resource": "$TOPIC_ARN" },
    { "Effect": "Allow", "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"], "Resource": "*" }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name route53-monthly-export-inline \
  --policy-document file://perm-policy.json

5) Create the Lambda function
aws lambda create-function \
  --function-name "$FUNC_NAME" \
  --zip-file fileb://function.zip \
  --handler lambda_function.lambda_handler \
  --runtime python3.11 \
  --role "arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME" \
  --environment "Variables={\
ORG_ROLE_NAME=$ORG_ROLE_NAME,\
REPORT_BUCKET=$BUCKET,\
REPORT_PREFIX=$REPORT_PREFIX,\
SNS_TOPIC_ARN=$TOPIC_ARN,\
PRESIGN_TTL_SEC=$PRESIGN_TTL_SEC}" \
  --timeout 900 \
  --memory-size 512 \
  --region "$REGION"

Update code later
zip -r function.zip lambda_function.py
aws lambda update-function-code --function-name "$FUNC_NAME" --zip-file fileb://function.zip --region "$REGION"

6) Test the Lambda manually
aws lambda invoke --function-name "$FUNC_NAME" --payload '{}' out.json --region "$REGION"
cat out.json


Check CloudWatch Logs for the function (errors/warnings).

SNS subscribers should receive an email with the summary and a pre-signed S3 link.

Click the link — it should download the CSV even though the bucket is private.

7) Schedule it monthly (EventBridge)

Run on the 1st of each month @ 08:00 UTC:

RULE_NAME="Route53MonthlyExport"

aws events put-rule \
  --name "$RULE_NAME" \
  --schedule-expression "cron(0 8 1 * ? *)" \
  --region "$REGION"

aws events put-targets \
  --rule "$RULE_NAME" \
  --targets "Id"="1","Arn"="arn:aws:lambda:$REGION:$ACCOUNT_ID:function:$FUNC_NAME" \
  --region "$REGION"

aws lambda add-permission \
  --function-name "$FUNC_NAME" \
  --statement-id evt-allow \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:$REGION:$ACCOUNT_ID:rule/$RULE_NAME" \
  --region "$REGION"

8) Quick troubleshooting

SNS email not received: recipients must confirm the SNS subscription email. Also check spam; sender is no-reply@sns.amazonaws.com.

AccessDenied on pre-signed URL: verify the object exists in S3 and the link isn’t expired. (Default TTL is 7 days.)

AssumeRole fails: confirm each member account has the role $ORG_ROLE_NAME with trust to your audit account (or specifically to your Lambda’s role) and permissions route53:ListHostedZones + route53:ListResourceRecordSets.

Timeouts with many accounts/zones: increase Lambda memory (helps CPU/network) and timeout.

Bucket policy: not needed to make public; keep Block Public Access ON. Access is via pre-signed URLs only.

9) (Optional) Tighten S3 to prefix

If you want to limit Lambda to a prefix:

# Change the S3 Resource ARNs in perm-policy.json to:
# "arn:aws:s3:::$BUCKET",
# "arn:aws:s3:::$BUCKET/${REPORT_PREFIX%/}/*"


Re-apply with aws iam put-role-policy ....
