---
paths:
  - "infra/**"
  - "**/*.tf"
  - "**/*.tfvars"
  - ".github/**"
---

# Infrastructure and CI conventions (Terraform, AWS, GitHub Actions)

- Everything in AWS is created by Terraform. No console changes, no CLI-created resources.
- Never run `terraform apply` or `terraform destroy`. Run `terraform fmt`, `validate`, and `plan`, then present the plan output for review.
- Remote state in S3 with locking. Pin provider and Terraform versions.
- GitHub Actions authenticate to AWS with OIDC federation and a role scoped to one job. No long-lived access keys anywhere.
- Least privilege: one IAM role per component, actions listed explicitly, resources scoped by ARN. No `"*"` actions.
- Secrets live in AWS Secrets Manager or SSM Parameter Store and are read at runtime. No secrets in tfvars, workflow files, or Lambda environment variables in plain text.
- Cost: prefer serverless and free-tier services. Flag anything with an hourly charge before adding it.
- Tag every resource with `project` and `environment`.
- CI runs lint, typecheck, tests, and build for both `app/` and `api/` on every push and pull request.
