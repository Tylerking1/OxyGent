"""Unit tests for the code interpreter tools."""

import pytest

from oxygent.preset_tools.code_interpreter_tools import code_interpreter_tools


@pytest.mark.asyncio
async def test_execute_code_simple():
    session_id = "test_session_1"
    _, execute_code = code_interpreter_tools.func_dict["execute_code"]
    _, stop_session = code_interpreter_tools.func_dict["stop_session"]

    result = await execute_code(session_id=session_id, code="a = 10; print(a)")
    assert "10" in result
    await stop_session(session_id=session_id)


@pytest.mark.asyncio
async def test_execute_code_stateful():
    session_id = "test_session_2"
    _, execute_code = code_interpreter_tools.func_dict["execute_code"]
    _, stop_session = code_interpreter_tools.func_dict["stop_session"]

    await execute_code(session_id=session_id, code="x = 20")
    result = await execute_code(session_id=session_id, code="print(x * 2)")
    assert "40" in result
    await stop_session(session_id=session_id)


@pytest.mark.asyncio
async def test_execute_code_error():
    session_id = "test_session_3"
    _, execute_code = code_interpreter_tools.func_dict["execute_code"]
    _, stop_session = code_interpreter_tools.func_dict["stop_session"]

    # No warm-up: validate first-call error behavior without preheating
    result = await execute_code(session_id=session_id, code="print(undefined_variable)")
    assert "NameError" in result
    await stop_session(session_id=session_id)
