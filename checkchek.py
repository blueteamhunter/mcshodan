🧩 Step 1 — Verify your environment variables

These must still be in your shell from before. Check:

echo $FUNC_NAME $REGION $ACCOUNT_ID $ROLE_NAME $BUCKET $REPORT_PREFIX $SNS_TOPIC_ARN $ORG_ROLE_NAME


If any are empty, re-export them (replace with your real values):

export REGION="us-east-1"
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export FUNC_NAME="route53-monthly-export"
export ROLE_NAME="route53-monthly-export-role"
export BUCKET="org-dns-reports-$ACCOUNT_ID"
export REPORT_PREFIX="route53/monthly/"
export ORG_ROLE_NAME="OrgRoute53ReadRole"
export SNS_TOPIC_ARN="arn:aws:sns:$REGION:$ACCOUNT_ID:route53-monthly-dns-report"
export PRESIGN_TTL_SEC="604800"

🧱 Step 2 — Zip the new code

In the same folder as lambda_function.py:

rm -f function.zip
zip -r function.zip lambda_function.py


✅ You should see:

  adding: lambda_function.py (deflated 70%)

🚀 Step 3 — Update the Lambda function code

If the Lambda already exists:

aws lambda update-function-code \
  --function-name "$FUNC_NAME" \
  --zip-file fileb://function.zip \
  --region "$REGION"


You should see:

{
    "FunctionName": "route53-monthly-export",
    "LastModified": "2025-10-09T22:12:33.123+0000",
    ...
}

⚙️ Step 4 — Update Lambda environment variables (just to be safe)

This ensures your new code has all the correct env vars.

aws lambda update-function-configuration \
  --function-name "$FUNC_NAME" \
  --environment "Variables={\
ORG_ROLE_NAME=$ORG_ROLE_NAME,\
REPORT_BUCKET=$BUCKET,\
REPORT_PREFIX=$REPORT_PREFIX,\
SNS_TOPIC_ARN=$SNS_TOPIC_ARN,\
PRESIGN_TTL_SEC=$PRESIGN_TTL_SEC}" \
  --timeout 900 \
  --memory-size 512 \
  --region "$REGION"


Wait 10–20 seconds for AWS to apply the new configuration.

🧪 Step 5 — Invoke and test the Lambda
aws lambda invoke \
  --function-name "$FUNC_NAME" \
  --payload '{}' \
  --region "$REGION" \
  out.json && cat out.json


✅ Expected:

{
  "accountsProcessed": 3,
  "rowsInMaster": 274,
  "masterKey": "route53/monthly/2025-10-09/ALL.csv",
  "presignedUrlTTLSeconds": 604800
}

📜 Step 6 — Tail logs to confirm clean execution
aws logs tail "/aws/lambda/$FUNC_NAME" --follow --since 15m --region "$REGION"


You should see lines like:

Found 3 active accounts
Account workload-dev (111111111111): zones=5 records=47
Account workload-prod (222222222222): zones=8 records=113
Done: {"accountsProcessed": 3, "rowsInMaster": 274, "masterKey": "route53/monthly/2025-10-09/ALL.csv"}

📬 Step 7 — Verify email

You’ll receive a clean SNS email that looks like this:

Route 53 Monthly Export — 2025-10-09

Summary (Account, Id, Zones, Records):
- workload-dev, 111111111111, 5, 47
- workload-prod, 222222222222, 8, 113

Master CSV link (valid for 7 days):
<https://org-dns-reports-123456789012.s3.amazonaws.com/route53/monthly/2025-10-09/ALL.csv?...signature...>

If the link looks broken, copy EVERYTHING between the angle brackets on the line above.


If you copy the link between the brackets and paste it into a browser, ✅ it should immediately download your ALL.csv.

🧰 Step 8 — (Optional) Confirm the file exists on S3
TODAY_UTC=$(date -u +%F)
aws s3 ls "s3://$BUCKET/$REPORT_PREFIX$TODAY_UTC/" --region "$REGION"


You should see:

2025-10-09  20:22:15     123456 route53_dev_111111111111.csv
2025-10-09  20:22:16     543210 route53_prod_222222222222.csv
2025-10-09  20:22:16     789012 ALL.csv

✅ At this point

You have:

New patched Lambda deployed

S3 bucket populated with CSVs

SNS email with a clean presigned URL that should work perfectl
