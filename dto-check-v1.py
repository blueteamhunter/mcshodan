🧾 AWS Route 53 DNS Audit – Automated Reporting Architecture

Epic: Cloud Compliance & Governance
Component: AWS Automation / Lambda / S3 / SNS
Owner: DevOps Team
Status: ✅ Operational

🧩 Summary

This architecture automates the monthly export of Route 53 DNS zones and records from two AWS member accounts into a centralized S3 bucket, generating a master CSV report, and notifying stakeholders via SNS email.

All operations run serverlessly (Lambda) and respect least-privilege cross-account IAM roles.
The process avoids any persistent compute cost and runs on demand or via a scheduled EventBridge rule.

🏗️ Architecture Overview

Main Components

Component	Purpose
AWS Lambda (Audit Function)	Central function that assumes cross-account roles, exports Route 53 hosted zones and records, consolidates data, and sends SNS email notification.
AWS Organizations	Provides account management context (optional). In this deployment, the Lambda is locked to two specific accounts (B & C).
Cross-Account IAM Role (OrgRoute53ReadRole)	Deployed in member accounts (B & C). Grants minimal permissions to list Route 53 zones and records.
Central S3 Bucket	Stores per-account CSVs and a consolidated ALL.csv master report.
SNS Topic	Sends an email notification containing a summary and the presigned S3 URL for download.
EventBridge Rule (optional)	Triggers the Lambda on the 1st of each month to automate reporting.
🧠 Data Flow

Lambda Execution
The main Lambda (route53-monthly-export) is manually invoked or triggered by schedule.

Account Targeting
The function uses the environment variable ALLOWED_ACCOUNT_IDS (comma-separated) to define which member accounts to query.
It never calls organizations:ListAccounts unless explicitly allowed.

Cross-Account Role Assumption
For each target account:

Lambda assumes arn:aws:iam::<ACCOUNT_ID>:role/OrgRoute53ReadRole

That role has route53:ListHostedZones and route53:ListResourceRecordSets permissions.

Data Collection
Each account’s hosted zones and records are retrieved via AWS SDK (boto3).
Data is written to memory and serialized as CSV:

route53_<account_name>_<account_id>.csv


Master Consolidation
All rows are merged into a single file:

route53/monthly/<yyyy-mm-dd>/ALL.csv


S3 Storage
CSVs are uploaded to a secure private S3 bucket (org-dns-reports-<account>).
Bucket access is limited to the Lambda execution role and security administrators.

Notification & Distribution
Lambda generates a presigned S3 URL (valid 7 days) and publishes a message to an SNS topic.
The message includes:

Summary of zones and record counts per account

The download URL enclosed in angle brackets for better formatting

Email Delivery
SNS sends plain-text emails to subscribed recipients.
(Note: Outlook Safe Links may rewrite URLs; customers can whitelist the sender or domain.)

🔐 Security Model
Layer	Control	Description
Lambda IAM Role	Scoped to minimum S3/SNS/STS permissions	Can only AssumeRole into specific account ARNs and access the report bucket.
Member Account Role (OrgRoute53ReadRole)	Scoped read-only	Allows only DNS listing actions, denies modifications.
S3 Bucket Policy	Private	No public access; presigned URLs expire automatically.
SNS Topic	Internal	Used for notification only, no external subscriptions.
Data Sensitivity	Low	Contains DNS record metadata (no PII).
⚙️ Deployment Variables
Variable	Example	Description
ORG_ROLE_NAME	OrgRoute53ReadRole	Role name to assume in target accounts
REPORT_BUCKET	org-dns-reports-123456789012	Centralized private S3 bucket
REPORT_PREFIX	route53/monthly/	Folder prefix for reports
SNS_TOPIC_ARN	arn:aws:sns:us-east-1:123456789012:route53-monthly-dns-report	SNS topic for notifications
PRESIGN_TTL_SEC	604800	Presigned URL expiration (seconds)
ALLOWED_ACCOUNT_IDS	111111111111,222222222222	Explicit account allowlist
FORCE_ALLOWED_ONLY	true	Prevents fallback to Organization listing
🧾 Example S3 Structure
s3://org-dns-reports-123456789012/
└── route53/
    └── monthly/
        └── 2025-10-09/
            ├── route53_workload-dev_111111111111.csv
            ├── route53_workload-prod_222222222222.csv
            └── ALL.csv

📨 Example SNS Email
Subject: [Route53] Monthly DNS Export 2025-10-09

Route 53 Monthly Export — 2025-10-09

Summary (Account, Id, Zones, Records):
- workload-dev, 111111111111, 4, 96
- workload-prod, 222222222222, 6, 214

Master CSV link (valid for 7 days):
<https://org-dns-reports-123456789012.s3.amazonaws.com/route53/monthly/2025-10-09/ALL.csv?...>

If the link looks broken, copy EVERYTHING between the angle brackets on the line above.

🧰 IAM Policy Summary (Lambda Execution Role)
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": [
        "arn:aws:iam::111111111111:role/OrgRoute53ReadRole",
        "arn:aws:iam::222222222222:role/OrgRoute53ReadRole"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::org-dns-reports-123456789012", "arn:aws:s3:::org-dns-reports-123456789012/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["sns:Publish"],
      "Resource": "arn:aws:sns:us-east-1:123456789012:route53-monthly-dns-report"
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],
      "Resource": "*"
    }
  ]
}

🧮 Cost & Maintenance
Service	Description	Estimated Monthly Cost
Lambda	< 1M invocations/month	≈ $0.00 (free tier)
S3	CSV storage (<5 MB per run)	< $0.10/month
SNS	Few messages/month	Negligible
CloudWatch Logs	Execution logs	< $1/month
Total		<$2/month
🧱 Deployment Steps (Summary)

Create central S3 bucket

Create SNS topic and email subscription

Deploy OrgRoute53ReadRole to target accounts (B & C)

Deploy Lambda function route53-monthly-export

Configure environment variables & IAM policy

Test invocation (aws lambda invoke ...)

(Optional) Add EventBridge rule for monthly schedule

🧩 Known Limitations

Presigned URL rewriting: Outlook Safe Links may corrupt links — customers can whitelist or request an alternate delivery mechanism (SES, API Gateway redirect, etc.)

IAM dependency: Role name OrgRoute53ReadRole must exist in all target accounts.

Execution time: Large Route 53 datasets may require increasing Lambda timeout (default 900 s).

Single region: Reports assume Route 53 is global (no regional separation).

✅ Validation Checklist
Item	Status	Notes
Lambda deployed and tested	✅	out.json returns presigned URL
S3 bucket receives per-account + master CSVs	✅	Files visible under correct prefix
Email notification delivered	✅	Validated via SNS subscription
Presigned URL downloads successfully	✅	Tested manually
IAM permissions scoped	✅	AssumeRole limited to B & C
Logging and traceability enabled	✅	CloudWatch active
🚀 Next Steps / Future Enhancements

 Add optional SES HTML report for safer email delivery

 Implement Lambda@Edge redirect for friendly short URLs

 Extend to additional AWS accounts if required

 Automate deployment via Terraform or CDK

Document Version: 1.0
Last Updated: 2025-10-09
Prepared by: 🧑‍💻 DevOps (AWS Automation Lead)
Reviewed by: ☑ Cloud Security

Would you like me to also generate a diagram (PlantUML / Lucidchart style) for this setup that you can paste into Jira’s “Diagrams” section?

You said:
Yes
DevOps GPT said:

Awesome — here are ready-to-paste diagrams for Jira. I’ve included both PlantUML (common in Jira via the PlantUML plugin) and Mermaid (native in newer Jira/Confluence). Use whichever your instance supports.

PlantUML – Architecture (Component) Diagram
@startuml
title AWS Route53 DNS Audit – Architecture Overview

skinparam shadowing false
skinparam componentStyle rectangle
skinparam wrapWidth 200
skinparam defaultTextAlignment center

actor "Stakeholders\n(Email Recipients)" as Recipients

package "Audit Account (Central)" {
  [EventBridge\nMonthly Schedule] as EB
  component "Lambda\nroute53-monthly-export" as Lambda
  [SNS Topic\nroute53-monthly-dns-report] as SNS
  [S3 Bucket\norg-dns-reports-<acct>]" as S3

  node "IAM (Audit Exec Role)" as AuditRole
}

cloud "AWS Organizations" as Orgs

package "Member Account B" {
  node "IAM Role\nOrgRoute53ReadRole" as RoleB
  [Route 53 (Global)\nZones & Records] as R53B
}

package "Member Account C" {
  node "IAM Role\nOrgRoute53ReadRole" as RoleC
  [Route 53 (Global)\nZones & Records] as R53C
}

EB -down-> Lambda : cron(0 8 1 * ? *)\n(optional)
Orgs -[hidden]- Lambda

Lambda -right-> RoleB : STS:AssumeRole
Lambda -right-> RoleC : STS:AssumeRole

RoleB -down-> R53B : ListHostedZones\nListResourceRecordSets
RoleC -down-> R53C : ListHostedZones\nListResourceRecordSets

Lambda -down-> S3 : PutObject\n(per-account CSVs + ALL.csv)
Lambda -down-> SNS : Publish\n(summary + presigned URL)

SNS -down-> Recipients : Email\n(plain text)

note right of Lambda
Env Vars:
- ORG_ROLE_NAME=OrgRoute53ReadRole
- REPORT_BUCKET
- REPORT_PREFIX
- SNS_TOPIC_ARN
- PRESIGN_TTL_SEC (default 604800)
- ALLOWED_ACCOUNT_IDS="B_ID,C_ID"
- FORCE_ALLOWED_ONLY=true
end note

note left of AuditRole
Lambda Execution Role:
- sts:AssumeRole -> B/C only
- s3:Put/Get/List -> report bucket/prefix
- sns:Publish -> topic
- logs:* -> *
end note

@enduml

PlantUML – Sequence Diagram (Monthly Run Flow)
@startuml
title Route53 Audit – Monthly Execution Flow

skinparam shadowing false
skinparam ParticipantPadding 20
skinparam BoxPadding 10

actor User as U
participant "EventBridge\n(Schedule)" as EB
participant "Lambda\nroute53-monthly-export" as L
participant "STS\n(AssumeRole)" as STS
participant "Member Acc B:\nOrgRoute53ReadRole" as RB
participant "Member Acc C:\nOrgRoute53ReadRole" as RC
participant "Route53 (Global)\nB" as R53B
participant "Route53 (Global)\nC" as R53C
database "S3\nReports Bucket" as S3
queue "SNS Topic" as SNS
actor "Email Recipients" as Recipients

== Trigger ==
U -> EB : (optional) On-demand test\n—or— Monthly cron
EB -> L : Invoke()

== Account Targeting ==
L -> L : Read ALLOWED_ACCOUNT_IDS\n(FORCE_ALLOWED_ONLY=true)\n-> [B_ID,C_ID]

== Account B ==
L -> STS : AssumeRole(B_ID/OrgRoute53ReadRole)
STS --> L : Temp creds
L -> R53B : list_hosted_zones / list_resource_record_sets
L -> S3 : PutObject(route53_B_*.csv)

== Account C ==
L -> STS : AssumeRole(C_ID/OrgRoute53ReadRole)
STS --> L : Temp creds
L -> R53C : list_hosted_zones / list_resource_record_sets
L -> S3 : PutObject(route53_C_*,csv)

== Consolidate ==
L -> S3 : PutObject(ALL.csv)
L -> L : Generate presigned URL (TTL)

== Notify ==
L -> SNS : Publish(summary + URL)
SNS -> Recipients : Send email

@enduml

Mermaid – Architecture Diagram (Alternative)
flowchart TB
  subgraph Audit["Audit Account (Central)"]
    EB[EventBridge\nMonthly Schedule]
    L[Lambda\nroute53-monthly-export]
    S3[(S3 Bucket\norg-dns-reports-<acct>)]
    SNS[[SNS Topic\nroute53-monthly-dns-report]]
  end

  subgraph B["Member Account B"]
    RB[ IAM Role\nOrgRoute53ReadRole ]
    R53B[Route 53 (Global)\nZones & Records]
  end

  subgraph C["Member Account C"]
    RC[ IAM Role\nOrgRoute53ReadRole ]
    R53C[Route 53 (Global)\nZones & Records]
  end

  Recipients[[Email Recipients]]

  EB --> L
  L -->|STS:AssumeRole| RB
  L -->|STS:AssumeRole| RC
  RB -->|ListHostedZones / ListRRsets| R53B
  RC -->|ListHostedZones / ListRRsets| R53C
  L -->|PutObject per-account + ALL.csv| S3
  L -->|Publish summary + presigned URL| SNS
  SNS --> Recipients

Mermaid – Sequence Diagram (Alternative)
sequenceDiagram
  autonumber
  actor User as User (optional)
  participant EB as EventBridge (Schedule)
  participant L as Lambda (route53-monthly-export)
  participant STS as STS (AssumeRole)
  participant RB as Role B (OrgRoute53ReadRole)
  participant RC as Role C (OrgRoute53ReadRole)
  participant R53B as Route53 (B)
  participant R53C as Route53 (C)
  participant S3 as S3 (Reports)
  participant SNS as SNS Topic
  actor R as Email Recipients

  User->>EB: Manual test (optional)
  EB->>L: Invoke()

  Note over L: Read env vars:\nALLOWED_ACCOUNT_IDS=B_ID,C_ID\nFORCE_ALLOWED_ONLY=true

  L->>STS: AssumeRole(B_ID/OrgRoute53ReadRole)
  STS-->>L: Temp creds
  L->>R53B: list zones + records
  L->>S3: PutObject(route53_B_*.csv)

  L->>STS: AssumeRole(C_ID/OrgRoute53ReadRole)
  STS-->>L: Temp creds
  L->>R53C: list zones + records
  L->>S3: PutObject(route53_C_*.csv)

  L->>S3: PutObject(ALL.csv)
  L->>L: Generate presigned URL (TTL)

  L->>SNS: Publish(summary + URL)
  SNS-->>R: Email notification
