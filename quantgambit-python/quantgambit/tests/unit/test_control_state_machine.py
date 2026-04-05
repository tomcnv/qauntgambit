from quantgambit.control.failover import FailoverStateMachine, FailoverState


def test_failover_state_machine_flow():
    sm = FailoverStateMachine()
    assert sm.context.state == FailoverState.PRIMARY_ACTIVE

    sm.apply("FAILOVER_ARM")
    assert sm.context.state == FailoverState.FAILOVER_ARMED

    sm.apply("FAILOVER_EXEC")
    assert sm.context.state == FailoverState.SECONDARY_ACTIVE

    sm.apply("RECOVER_ARM")
    assert sm.context.state == FailoverState.RECOVERY_PENDING

    sm.apply("RECOVER_EXEC")
    assert sm.context.state == FailoverState.PRIMARY_ACTIVE


def test_failover_halt():
    sm = FailoverStateMachine()
    sm.apply("HALT")
    assert sm.context.state == FailoverState.HALTED
    sm.apply("FAILOVER_ARM")
    assert sm.context.state == FailoverState.HALTED

