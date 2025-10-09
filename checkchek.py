No stress — we’ll fix both symptoms:

masterKey empty in the Lambda result

Email link shows AccessDenied … requires the signature, Expires, X-Amz-Algorithm, X-Amz-Credential, X-Amz-Signature… (i.e., URL got mangled)

Let’s troubleshoot quickly, then I’ll give you a small hot-fix you can push.

A) Quick diagnostics (bash on Ubuntu/WSL)
1) Make sure you’re invoking the right function in the right region
aws lambda get-function --function-name "$FUNC_NAME" --region "$REGION" \
  --query 'Configuration.[FunctionName,LastModified,Version,Role]' --output table

2) Re-invoke and print the function’s own return
aws lambda invoke --function-name "$FUNC_NAME" --payload '{}' --region "$REGION" out.json
cat out.json


If masterKey is empty here, we need logs.

3) Tail logs for the latest run
aws logs tail "/aws/lambda/$FUNC_NAME" --follow --since 15m --region "$REGION"


Look for the final log line starting with Done: — it should include masterKey.
If masterKey is empty there too, check env vars:

4) Verify Lambda environment variables set on AWS
aws lambda get-function-configuration \
  --function-name "$FUNC_NAME" --region "$REGION" \
  --query 'Environment.Variables' --output table


You should see:

REPORT_BUCKET = your bucket name

REPORT_PREFIX = route53/monthly/ (trailing slash OK)

SNS_TOPIC_ARN populated

ORG_ROLE_NAME populated

5) Check S3 actually has the files (UTC date!)
TODAY_UTC=$(date -u +%F)
aws s3 ls "s3://$BUCKET/$REPORT_PREFIX$TODAY_UTC/" --region "$REGION" || true


If you see ALL.csv, the object exists — the email link was just mangled.
You can test a manual presign to confirm:

aws s3 presign "s3://$BUCKET/$REPORT_PREFIX$TODAY_UTC/ALL.csv" --expires-in 3600 --region "$REGION"


Open that URL in your browser; it should download directly.

B) Why the email link breaks (and the fast fix)

SNS sends plain-text emails. Many clients wrap long lines, splitting the presigned URL and stripping query params → you get the “signature required” error. We already shortened the key to ALL.csv and put the URL in angle brackets, but some clients still break extremely long links.

Minimal hot-fix: shorten the bucket name and prefix

Bucket names like org-dns-reports-123456789012 are fine, but if you can use something shorter (e.g., r53rpt-<acct>), do it.

Use a short prefix like r/ instead of route53/monthly/.

After changing the bucket/prefix in env vars, redeploy the config:

export REPORT_PREFIX="r/"
aws lambda update-function-configuration \
  --function-name "$FUNC_NAME" \
  --environment "Variables={\
ORG_ROLE_NAME=$ORG_ROLE_NAME,\
REPORT_BUCKET=$BUCKET,\
REPORT_PREFIX=$REPORT_PREFIX,\
SNS_TOPIC_ARN=$SNS_TOPIC_ARN,\
PRESIGN_TTL_SEC=$PRESIGN_TTL_SEC}" \
  --timeout 900 --memory-size 512 --region "$REGION"


Re-invoke and test.

C) Small code hot-patch for extra robustness (optional but recommended)

This adds explicit logging of master_key and ensures it’s never empty. It also prints the presigned URL length to logs (to confirm email wrapping risk). If you want, apply this tiny edit to your lambda_function.py:

Find the block where we create the master file and build the SNS message, and replace with:

# 3) Master CSV with short key + pre-signed URL
date_prefix = f"{_normalize_prefix(REPORT_PREFIX)}{stamp}/"
master_key  = f"{date_prefix}ALL.csv"

# Guard: never allow empty/None
if not master_key.strip():
    raise RuntimeError("master_key resolved empty; check REPORT_PREFIX and stamp")

s3_put(master_key, rows_to_csv_bytes(master_rows))
master_link = s3_presign(master_key)

# Log lengths to help diagnose email wrapping
logger.info("Master key: %s", master_key)
logger.info("Presigned URL length: %d", len(master_link))

# 4) Minimal SNS message with angle-bracketed link
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

publish_sns(subject=f"[Route53] Monthly DNS Export {stamp}", message=message)

result = {
    "accountsProcessed": len(accounts),
    "rowsInMaster": len(master_rows),
    "masterKey": master_key,
    "presignedUrlTTLSeconds": PRESIGN_TTL_SEC
}
logger.info("Done: %s", json.dumps(result))
return result


Then redeploy:

rm -f function.zip
zip -r function.zip lambda_function.py
aws lambda update-function-code --function-name "$FUNC_NAME" --zip-file fileb://function.zip --region "$REGION"


Re-invoke, tail logs, and re-check S3 + email.

D) If the link still breaks in email

When presigned URLs are still too long for your email client, the bulletproof fix is to email a short redirect URL (via a tiny Lambda Function URL that 302-redirects to the fresh presigned link). I can give you the 5-minute deploy for that if needed — but try the shorter bucket/prefix + this hot-patch first.

Summary

masterKey empty → check logs and env vars; the patch logs master key/URL length and guards empty values.

Broken link → your email client wrapped the URL; shorten bucket/prefix and keep the link on its own line in angle brackets.

Manual aws s3 presign ... confirms the object is accessible — proving it’s an email formatting issue, not S3 permissions.
