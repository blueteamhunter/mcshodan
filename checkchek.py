1) Make sure your basics are set
echo "$REGION" "$ACCOUNT_ID" "$TOPIC_NAME"
aws sts get-caller-identity


If TOPIC_NAME isn’t set yet:

export TOPIC_NAME="route53-monthly-dns-report"

2) Get (or create) the topic ARN and export it

This is idempotent: if the topic exists, it returns the ARN; if not, it creates it and returns the ARN.

export TOPIC_ARN=$(aws sns create-topic \
  --name "$TOPIC_NAME" \
  --region "$REGION" \
  --query TopicArn --output text)

echo "TOPIC_ARN=$TOPIC_ARN"


If that prints (None) or empty:

Double-check region: echo "$REGION"

Ensure your CLI identity is the audit account you expect.

3) (Optional) Verify subscribers (must be Confirmed)
aws sns list-subscriptions-by-topic \
  --topic-arn "$TOPIC_ARN" --region "$REGION" \
  --query 'Subscriptions[].{Endpoint:Endpoint,Protocol:Protocol,Arn:SubscriptionArn}' \
  --output table


If you need to add subscribers:

aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint it-team@yourco.com --region "$REGION"

4) Update the Lambda’s environment with the fixed ARN

You can re-set all env vars you already exported (simplest & safe):

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

5) Sanity test: publish to SNS
aws sns publish \
  --topic-arn "$TOPIC_ARN" \
  --subject "Route53 report test" \
  --message "This is a test from CLI." \
  --region "$REGION"


Recipients should get a test email (if confirmed).

6) Invoke the Lambda again
aws lambda invoke \
  --function-name "$FUNC_NAME" \
  --payload '{}' \
  --region "$REGION" \
  out.json && cat out.json


Then check your email for the SNS message with the pre-signed link, and list the S3 folder for today:

TODAY_UTC=$(date -u +%F)
aws s3 ls "s3://$BUCKET/$REPORT_PREFIX$TODAY_UTC/" --region "$REGION"


If TOPIC_ARN is still not populating, tell me what echo "$TOPIC_ARN" prints and any error from the create-topic command, and I’ll pinpoint the fix.
