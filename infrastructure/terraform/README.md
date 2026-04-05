# QuantGambit Single-EC2 Terraform

This stack replaces the previous multi-service AWS footprint with a single-host deployment in `ap-southeast-1` that is designed to stay near your `$400/month` ceiling.

## What Terraform Creates

- A dedicated VPC with one public subnet in Singapore
- One `m7i-flex.2xlarge` EC2 instance on Amazon Linux 2023
- One encrypted `gp3` root volume sized for app code, Docker layers, Redis, and both Postgres databases
- One Elastic IP
- Route 53 `A` records for:
  - `quantgambit.com`
  - `www.quantgambit.com`
  - `dashboard.quantgambit.com`
  - `api.quantgambit.com`
  - `bot.quantgambit.com`
- IAM instance profile for SSM Session Manager, CloudWatch Agent, and reading Secrets Manager / SSM config
- Baseline CloudWatch alarms for EC2 CPU and status checks

## What Terraform Explicitly Does Not Create

- NAT Gateway
- ALB / NLB
- ECS / EKS
- RDS
- ElastiCache
- ACM / CloudFront

Those services are what pushed the prior design above your budget.

## Cost Shape

The main cost driver is the EC2 host. AWS public price-list data for `ap-southeast-1` currently shows `m7i-flex.2xlarge` Linux on-demand at `$0.4788/hr`, which is about `$349.52/month` at 730 hours.

Expected monthly envelope:

- EC2 `m7i-flex.2xlarge`: about `$350`
- `gp3` storage: typically `$20-35`, depending on final volume size and provisioned performance
- Public IPv4 / Elastic IP: about `$3-4`
- Route 53 hosted zone and low-volume DNS queries: about `$1-3`
- CloudWatch logs / alarms / metrics: about `$5-15`

That keeps the redesigned stack roughly in the `$380-405` range on on-demand pricing. If you need consistent headroom below `$400`, use a 1-year Compute Savings Plan or trim the root volume size.

## Bootstrapping

The instance `user_data`:

- installs Docker, Nginx, Certbot, SSM, and CloudWatch Agent
- applies kernel and file-descriptor tuning
- enables an `8G` swap file
- configures Docker log rotation
- puts up a bootstrap Nginx page for all five hostnames

Application deployment is handled by [`deploy/single-ec2/deploy.sh`](../../deploy/single-ec2/deploy.sh).

## Typical Apply

```bash
cd infrastructure/terraform
terraform init -backend-config=backend/production.hcl
terraform plan -var-file=environments/production.tfvars
terraform apply -var-file=environments/production.tfvars
```

The repo now includes:

- [production.hcl](./backend/production.hcl)
- [production.hcl.example](./backend/production.hcl.example)
- [bootstrap-production-backend.sh](./backend/bootstrap-production-backend.sh)
- [production.auto.tfvars.example](./environments/production.auto.tfvars.example)

## First-Time Backend Bootstrap

Before `terraform init`, create the remote state bucket and lock table:

```bash
cd infrastructure/terraform
AWS_REGION=ap-southeast-1 ./backend/bootstrap-production-backend.sh
```

That script creates:

- S3 bucket `quantgambit-terraform-state`
- DynamoDB table `quantgambit-terraform-locks`

Both names match [production.hcl](./backend/production.hcl).

## Operator Vars

Create a real operator-owned tfvars file from:

- [production.auto.tfvars.example](./environments/production.auto.tfvars.example)

Recommended:

```bash
cp environments/production.auto.tfvars.example environments/production.auto.tfvars
```

Then fill at least:

- `copilot_llm_api_key`
- `copilot_llm_model`

If your runtime secrets are not under the default `deeptrader/prod/*` or `quantgambit/production/*` namespaces, also set:

- `secretsmanager_secret_arns`
- `ssm_parameter_arns`
- `kms_key_arns`

## Post-Apply

1. Open an SSM shell using the `ssm_start_session_command` output.
2. Clone or sync this repo onto the EC2 host.
3. Create `deploy/single-ec2/.env` from `deploy/single-ec2/.env.example`.
4. Or let `deploy/single-ec2/deploy.sh` fetch `.env` automatically from Secrets Manager if `APP_ENV_SECRET_ID` is present on the host.
5. Run `deploy/single-ec2/deploy.sh`.
6. Issue the certificate with:

```bash
sudo certbot --nginx \
  -d quantgambit.com \
  -d www.quantgambit.com \
  -d dashboard.quantgambit.com \
  -d api.quantgambit.com \
  -d bot.quantgambit.com
```

## Route 53 Notes

- `manage_route53_records=false` is the safe default in the checked-in tfvars. That keeps the stack deployable before DNS ownership is wired.
- Set `manage_route53_records=true` when you are ready for Terraform to manage the public records.
- Set `create_route53_zone=true` only if AWS should host the entire `quantgambit.com` public zone.
- If the zone already exists in Route 53, pass `existing_route53_zone_id`.
- If DNS is hosted outside Route 53, leave `manage_route53_records=false` and use the Elastic IP output manually.

## IAM Scope

The EC2 role now defaults to project/environment-scoped SSM and Secrets Manager ARNs instead of `*`.

- SSM defaults:
  - `arn:aws:ssm:<region>:<account>:parameter/quantgambit/<environment>/*`
  - `arn:aws:ssm:<region>:<account>:parameter/quantgambit/shared/*`
- Secrets Manager defaults:
  - `arn:aws:secretsmanager:<region>:<account>:secret:quantgambit/<environment>/*`
  - `arn:aws:secretsmanager:<region>:<account>:secret:quantgambit/shared/*`
- If you use custom paths or customer-managed KMS keys, override:
  - `ssm_parameter_arns`
  - `secretsmanager_secret_arns`
  - `kms_key_arns`

## Managed App Secret

When `manage_app_env_secret=true`, Terraform creates one secret containing the single-host deploy `.env` payload:

- secret name default:
  - `${project_name}/${environment}/single-ec2/app-env`

The deploy script will fetch that secret automatically when:

- `/opt/quantgambit/config/host.env.example` contains `APP_ENV_SECRET_ID`
- the EC2 role can read that secret

Important:

- Terraform-managed secret values are stored in Terraform state.
- That is acceptable only if your S3 backend is locked down and encrypted.
- Exchange API credentials remain separate and continue to live under the app-managed `deeptrader/...` namespace.
