# PM2 to ECS RunTask Migration Runbook

## Goal

Move dynamic bot runtime launch/stop from PM2 shell scripts to ECS `RunTask`, while preserving rollback.

## Current

- Control manager launches runtimes via shell scripts (`launch-runtime.sh`, `stop-runtime.sh`).
- PM2 manages long-running local processes.

## Target

- Control manager calls ECS API:
  - `RunTask` to start runtime
  - `StopTask` to stop runtime
- Runtime container image comes from ECR.
- Task networking in private subnets with ECS task SG.

## Migration Steps

1. Add runtime task definition in ECS (no service, on-demand only).
2. Add IAM permissions to control manager task role:
   - `ecs:RunTask`, `ecs:StopTask`, `ecs:DescribeTasks`, `iam:PassRole`.
3. Add config flags:
   - `CONTROL_LAUNCH_MODE=ecs|pm2`
   - `ECS_CLUSTER_NAME`, `ECS_RUNTIME_TASK_FAMILY`, `ECS_SUBNETS`, `ECS_SECURITY_GROUPS`.
4. Deploy with `CONTROL_LAUNCH_MODE=pm2` (no behavior change).
5. Enable `ecs` mode for one tenant/bot canary.
6. Monitor startup latency, task failures, and order continuity.
7. Roll out progressively by bot cohort.

## Rollback

- Switch `CONTROL_LAUNCH_MODE` back to `pm2`.
- Stop ECS runtime tasks for affected bots.
- Restart runtime launch through existing shell path.

## Success Criteria

- Runtime start success >= 99% over 24h.
- No increase in missed decisions due to runtime startup failures.
- No regression in execution/position reconciliation behavior.
