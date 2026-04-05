# Single-Host AWS Layout

```
Internet
  |
  +-- Route 53
        |
        +-- quantgambit.com
        +-- www.quantgambit.com
        +-- dashboard.quantgambit.com
        +-- api.quantgambit.com
        +-- bot.quantgambit.com
                |
                v
        Elastic IP on one EC2 instance
                |
                v
      Amazon Linux 2023 / m7i-flex.2xlarge
                |
                +-- Nginx on host
                |     +-- serves landing static files
                |     +-- serves dashboard static files
                |     +-- proxies api.quantgambit.com -> Node backend :3001
                |     +-- proxies bot.quantgambit.com -> Python API :3002
                |
                +-- Docker Compose
                      +-- postgres_platform
                      +-- timescale_bot
                      +-- redis
                      +-- deeptrader-backend
                      +-- quantgambit-api
                      +-- market-data-service-bybit
                      +-- market-data-service-bybit-spot
```

## Why This Fits The Budget

- No NAT Gateway
- No ALB
- No managed database or cache
- No inter-AZ traffic
- One public IP
- One tuned `gp3` volume instead of multiple managed data planes

## Operational Tradeoff

This is intentionally cost-first, not HA-first.

- If the instance dies, the whole platform is down until recovery.
- Local Redis and local Postgres are fast and cheap, but backups matter.
- You should snapshot the root volume and export logical Postgres backups to S3 on a schedule.
- Terraform state for this stack should live in an S3 backend with DynamoDB locking, not on an operator laptop.

## EC2 Tuning Choices

- `m7i-flex.2xlarge` gives `8 vCPU / 32 GiB`
- `gp3` root with elevated IOPS and throughput avoids burst-credit behavior
- Host Nginx terminates TLS and avoids the cost of an ALB
- Swap is present as a buffer, but the goal is to stay out of swap during normal load
- Docker log rotation is enabled to prevent disk bloat
