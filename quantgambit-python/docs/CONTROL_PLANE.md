# Control Plane (Draft)

## Overview
The control plane is isolated from the trading hot path. It accepts commands via
FastAPI, publishes them to Redis Streams, and a separate consumer applies them
in a safe, audited manner.

## Components
- `quantgambit.control.api.ControlAPI`
- `quantgambit.control.command_consumer.CommandConsumer`
- `quantgambit.control.failover.FailoverStateMachine`
- `quantgambit.execution.actions.ExecutionActionHandler`

## Safety Rules
- Destructive commands require `confirm_token`.
- Failover is manual (arm + execute).
- All commands are audited to Postgres when enabled.

## Failover Wiring
- `FAILOVER_ARM` sets targets on the execution manager.
- `FAILOVER_EXEC` triggers the exchange router to swap adapters.

## Hot Path Guarantees
- No control-plane logic runs in the decision loop.
- Redis Streams and FastAPI operate on separate tasks/processes.
