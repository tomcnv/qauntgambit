# Infrastructure Plan (AWS Terraform)

## Targets
- Redis (ElastiCache) for command streams + snapshots
- Postgres (RDS) for audit tables + persistent logs
- TimescaleDB for high-volume trading telemetry (decisions, fills, latency)

## Terraform Scope
- VPC + subnets (private for Redis/RDS)
- Security groups
- ElastiCache Redis cluster
- RDS Postgres instance
- Parameter groups + backups
- IAM roles for deployment

## Phased Rollout
1) Terraform baseline (VPC, subnets, SGs)
2) RDS Postgres (db.t3.medium or similar)
3) ElastiCache Redis (cache.t3.medium or similar)
4) Outputs for app config (host/port)
5) TimescaleDB (managed or self-hosted) for telemetry

## Bot Runtime Sizing (Initial Guidance)

Dedicated task per bot is recommended for production hot-path performance.

Suggested tiers:
- **Test/Dev**: 2 vCPU / 4–8 GB RAM
- **Baseline Prod**: 4 vCPU / 8–16 GB RAM
- **High-Intensity**: 8 vCPU / 16–32 GB RAM
- **Heavy ML / Multi-Symbol**: 16 vCPU / 32–64 GB RAM

Autoscaling signals:
- Event loop lag (p99)
- Decision latency (p99)
- Memory pressure (% + GC pause time)
- Websocket message throughput

## AWS Runtime Model

Recommended: **ECS Fargate with one task per bot** for predictable latency.

Fallback: pooled workers only for staging/testing bots.

Planned Terraform additions:
- ECS cluster + task definition per tier (CPU/memory presets)
- Service autoscaling policies
- CloudWatch metrics + alarms for hot-path latency
- TimescaleDB instance (RDS Postgres + Timescale extension, or self-hosted EC2)

## Notes
- Use AWS Secrets Manager for credentials
- Enable automated backups + multi-AZ for production
- Allow inbound from app servers only
- Prefer dedicated trading DB (RDS + Timescale) separate from frontend/user DB
