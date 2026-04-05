# Deployment Phase Success Gates

## Phase 0: Bootstrap

- Terraform backend stack (`infra-bootstrap`) applies successfully.
- Remote state and lock table verified.

## Phase 1: Single-AZ Launch

Functional:
- Login and API health endpoints pass through ALB.
- Core workers stay healthy for 24h.
- Bot runtime start/stop path works for at least one bot.

Reliability:
- ALB 5xx remains below 1% (24h window).
- ECS task restart rate below 2 restarts/service/day.
- No sustained Redis or DB connection errors.

Cost:
- Estimated spend remains within launch band ($230-$560/month baseline).

## Phase 2: Runtime Orchestration Migration

Functional:
- ECS `RunTask` launch path replaces PM2 for canary cohort.

Reliability:
- Runtime launch success >= 99%.
- No increased reconciliation lag or decision drop rate.

Cost:
- Runtime orchestration does not increase monthly baseline by >15%.

## Phase 3: Hardening (HA)

Functional:
- Multi-AZ database and Redis failover tested.

Reliability:
- Survive single AZ failure without critical outage.

Cost:
- Post-HA spend approved against updated cost baseline and budget alarms.
