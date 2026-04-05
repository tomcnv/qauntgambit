# AWS Cost Baseline (Singapore, Single-AZ Launch)

Assumptions:
- Region: `ap-southeast-1`
- Single AZ launch footprint
- 24/7 core services, low bot count, moderate logs

## Monthly Estimate Bands

- ECS Fargate (API + bot API + workers): **$60-$140**
- ALB: **$20-$45**
- RDS (platform `db.t4g.small` + bot `db.t4g.medium`): **$80-$190**
- ElastiCache Redis (`cache.t4g.micro`): **$15-$40**
- NAT Gateway + egress: **$35-$90**
- CloudWatch + Secrets Manager + ECR + S3: **$15-$50**

## Total

- Lean launch: **$230-$560 / month**
- With moderate data/log growth: **$320-$700 / month**

## Top Cost Drivers

1. RDS class/storage growth
2. Fargate always-on compute hours
3. NAT data processing/egress
4. Log ingestion and retention

## Cost Guardrails

- Keep single-AZ until reliability gates are met.
- Keep Redis at `t4g.micro` and scale only on stream lag/memory pressure.
- Set `log_retention_days` to low default (7-14 days) for noisy streams.
- Use environment protections so destroy can remove unused stacks quickly.
