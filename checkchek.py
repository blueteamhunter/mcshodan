You got it. We’ll do just two things now: (1) set the env vars and (2) upload the Lambda code — all on Ubuntu/WSL (bash). No scheduling or extras yet.

1) Set variables (bash)

Paste this block, then edit the values that say <EDIT> if needed.

# ----- Core config -----
export REGION="us-east-1"                          # <EDIT if needed>

# Pull your current account id from your active CLI creds
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

# S3 bucket where reports are written (must exist or you’ll create it later)
export BUCKET="org-dns-reports-$ACCOUNT_ID"        # <EDIT if you chose a different name>

# SNS topic (must already exist) – use the full ARN
export TOPIC_ARN="arn:aws:sns:$REGION:$ACCOUNT_ID:route53-monthly-dns-report"  # <EDIT if your topic name differs>

# Lambda execution role (must already exist) – role in the *audit* account
export ROLE_NAME="route53-monthly-export-role"     # <EDIT if different>

# Lambda function name (new or existing)
export FUNC_NAME="route53-monthly-export"          # <EDIT if you want another name>

# Cross-account role name (in EACH member account)
export ORG_ROLE_NAME="OrgRoute53ReadRole"          # <EDIT only if you used a different name in member accts>

# S3 prefix (folder) for CSVs
export REPORT_PREFIX="route53/monthly/"

# Presigned URL TTL (seconds) – 7 days default
export PRESIGN_TTL_SEC="604800"

# ----- Sanity checks -----
echo "REGION        = $REGION"
echo "ACCOUNT_ID    = $ACCOUNT_ID"
echo "BUCKET        = $BUCKET"
echo "TOPIC_ARN     = $TOPIC_ARN"
echo "ROLE_NAME     = $ROLE_NAME"
echo "FUNC_NAME     = $FUNC_NAME"
echo "ORG_ROLE_NAME = $ORG_ROLE_NAME"
echo "REPORT_PREFIX = $REPORT_PREFIX"
echo "PRESIGN_TTL   = $PRESIGN_TTL_SEC"


Optional: persist these for future shells by appending to ~/.bashrc.

2) Upload the Lambda code

Make sure your file is named lambda_function.py and is in the current directory.

# Confirm the file is present
ls -l lambda_function.py

# Zip just that file (clean zip)
rm -f function.zip
zip -r function.zip lambda_function.py

Create the function (first time)

This will create the Lambda and set its environment variables.

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

OR Update the function (if it already exists)

Use this when you’re just pushing code changes or tweaking env vars.

# Update the code package
aws lambda update-function-code \
  --function-name "$FUNC_NAME" \
  --zip-file fileb://function.zip \
  --region "$REGION"

# (Re)set environment variables (idempotent)
aws lambda update-function-configuration \
  --function-name "$FUNC_NAME" \
  --environment "Variables={\
ORG_ROLE_NAME=$ORG_ROLE_NAME,\
REPORT_BUCKET=$BUCKET,\
REPORT_PREFIX=$REPORT_PREFIX,\
SNS_TOPIC_ARN=$TOPIC_ARN,\
PRESIGN_TTL_SEC=$PRESIGN_TTL_SEC}" \
  --timeout 900 \
  --memory-size 512 \
  --region "$REGION"

Quick verify (optional but handy)
aws lambda get-function --function-name "$FUNC_NAME" --region "$REGION" --query 'Configuration.[FunctionName,Runtime,Role,LastModified]' --output table
aws lambda get-function-configuration --function-name "$FUNC_NAME" --region "$REGION" --query 'Environment.Variables' --output table
