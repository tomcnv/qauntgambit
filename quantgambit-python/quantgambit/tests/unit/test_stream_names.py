import pytest

from quantgambit.storage.redis_streams import (
    command_stream_name,
    command_result_stream_name,
    control_command_stream_name,
    control_command_result_stream_name,
)


def test_command_stream_name_default():
    with pytest.raises(ValueError, match="command_stream_scope_required"):
        command_stream_name()


def test_command_stream_name_namespaced():
    assert command_stream_name("t1", "b1") == "commands:trading:t1:b1"


def test_command_result_stream_name_default():
    with pytest.raises(ValueError, match="command_result_stream_scope_required"):
        command_result_stream_name()


def test_command_result_stream_name_namespaced():
    assert command_result_stream_name("t1", "b1") == "events:command_result:t1:b1"


def test_control_command_stream_name_default():
    with pytest.raises(ValueError, match="control_command_stream_scope_required"):
        control_command_stream_name()


def test_control_command_stream_name_namespaced():
    assert control_command_stream_name("t1", "b1") == "commands:control:t1:b1"


def test_control_command_result_stream_name_default():
    with pytest.raises(ValueError, match="control_command_result_stream_scope_required"):
        control_command_result_stream_name()


def test_control_command_result_stream_name_namespaced():
    assert control_command_result_stream_name("t1", "b1") == "events:control_result:t1:b1"
