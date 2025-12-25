"""
Unit tests for OxyRequest.send_message method
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from oxygent.schemas import OxyRequest, SSEMessage


class MockMAS:
    """Mock MAS for testing send_message functionality"""
    
    def __init__(self):
        self.message_prefix = "test_msg"
        self.name = "test_mas"
        self.send_message = AsyncMock()
        self.func_process_message = lambda dict_message, oxy_request: dict_message
        self.reset_retry_attempt = MagicMock()
        self.increment_retry_attempt = MagicMock(return_value=1)
        self.get_retry_attempt = MagicMock(return_value=0)


@pytest.fixture
def mock_mas():
    return MockMAS()


@pytest.fixture
def oxy_request(mock_mas):
    """Create OxyRequest with mock MAS"""
    req = OxyRequest(
        arguments={"query": "test query"},
        caller="user",
        caller_category="user",
        current_trace_id="test_trace_123",
        group_id="test_group_456"
    )
    req.mas = mock_mas
    return req


@pytest.mark.asyncio
async def test_send_message_basic_functionality(oxy_request):
    """Test basic send_message functionality with all parameters"""
    test_message = {"type": "test", "content": "Hello World"}
    test_event = "test_event"
    test_id = "msg_123"
    test_retry = 5000
    
    await oxy_request.send_message(
        message=test_message,
        event=test_event,
        id=test_id,
        retry=test_retry
    )
    
    # Verify send_message was called
    assert oxy_request.mas.send_message.called
    
    # Get the arguments passed to send_message
    call_args = oxy_request.mas.send_message.call_args
    sse_message = call_args[0][0]
    redis_key = call_args[0][1]
    group_id = call_args[1]['group_id']
    
    # Verify SSEMessage content
    assert sse_message.data == test_message
    assert sse_message.event == test_event
    assert sse_message.id == test_id
    assert sse_message.retry == test_retry
    
    # Verify redis_key format
    expected_redis_key = f"{oxy_request.mas.message_prefix}:{oxy_request.mas.name}:{oxy_request.current_trace_id}"
    assert redis_key == expected_redis_key
    
    # Verify group_id
    assert group_id == oxy_request.group_id


@pytest.mark.asyncio
async def test_send_message_with_none_values(oxy_request):
    """Test send_message with None values for optional parameters"""
    test_message = {"type": "test", "content": "Test message"}
    
    await oxy_request.send_message(
        message=test_message,
        event=None,
        id=None,
        retry=None
    )
    
    call_args = oxy_request.mas.send_message.call_args
    sse_message = call_args[0][0]
    
    # None values should be filtered out
    assert sse_message.data == test_message
    assert sse_message.event is "message"
    assert sse_message.retry == 3000


@pytest.mark.asyncio
async def test_send_message_minimal_parameters(oxy_request):
    """Test send_message with only message parameter"""
    test_message = "Simple string message"
    
    await oxy_request.send_message(message=test_message)
    
    call_args = oxy_request.mas.send_message.call_args
    sse_message = call_args[0][0]
    
    assert sse_message.data == test_message
    assert sse_message.event is "message"
    assert sse_message.retry == 3000


@pytest.mark.asyncio
async def test_send_message_no_mas(oxy_request):
    """Test send_message when mas is None (should not send)"""
    oxy_request.mas = None
    
    await oxy_request.send_message(message="test message")
    
    # Should not crash when mas is None
    # No exception should be raised


@pytest.mark.asyncio
async def test_send_message_is_send_message_false(oxy_request):
    """Test send_message when is_send_message is False"""
    oxy_request.is_send_message = False
    
    await oxy_request.send_message(message="test message")
    
    # Should not send message when is_send_message is False
    assert not oxy_request.mas.send_message.called


@pytest.mark.asyncio
async def test_send_message_with_message_processing(oxy_request):
    """Test send_message with custom message processing"""
    def custom_process_message(dict_message, oxy_request):
        """Custom message processor that adds metadata"""
        processed = dict_message.copy()
        processed['data']['processed'] = True
        processed['data']['trace_id'] = oxy_request.current_trace_id
        return processed
    
    oxy_request.mas.func_process_message = custom_process_message
    
    test_message = {"type": "test", "content": "Original message"}
    
    await oxy_request.send_message(message=test_message)
    
    call_args = oxy_request.mas.send_message.call_args
    sse_message = call_args[0][0]
    
    # Verify message was processed
    assert sse_message.data['processed'] is True
    assert sse_message.data['trace_id'] == oxy_request.current_trace_id


@pytest.mark.asyncio
async def test_send_message_complex_data_types(oxy_request):
    """Test send_message with complex data types"""
    complex_message = {
        "type": "complex",
        "content": {
            "nested": {
                "array": [1, 2, 3],
                "object": {"key": "value"},
                "boolean": True,
                "null_value": None
            }
        },
        "metadata": {
            "timestamp": 1234567890,
            "source": "test"
        }
    }
    
    await oxy_request.send_message(
        message=complex_message,
        event="complex_event",
        id="complex_123"
    )
    
    call_args = oxy_request.mas.send_message.call_args
    sse_message = call_args[0][0]
    
    assert sse_message.data == complex_message
    assert sse_message.event == "complex_event"
    assert sse_message.id == "complex_123"


@pytest.mark.asyncio
async def test_send_message_empty_message(oxy_request):
    """Test send_message with empty/None message"""
    await oxy_request.send_message(message=None)
    
    call_args = oxy_request.mas.send_message.call_args
    sse_message = call_args[0][0]
    
    assert sse_message.data is ''


@pytest.mark.asyncio
async def test_send_message_string_message(oxy_request):
    """Test send_message with string message"""
    string_message = "This is a simple string message"
    
    await oxy_request.send_message(
        message=string_message,
        event="string_event",
        retry=3000
    )
    
    call_args = oxy_request.mas.send_message.call_args
    sse_message = call_args[0][0]
    
    assert sse_message.data == string_message
    assert sse_message.event == "string_event"
    assert sse_message.retry == 3000


@pytest.mark.asyncio
async def test_send_message_sse_message_creation(oxy_request):
    """Test that SSEMessage is created correctly from parameters"""
    test_data = {"test": "data"}
    
    await oxy_request.send_message(
        message=test_data,
        event="test_event",
        id="test_id",
        retry=1000
    )
    
    call_args = oxy_request.mas.send_message.call_args
    sse_message = call_args[0][0]
    
    # Verify it's an SSEMessage instance
    assert isinstance(sse_message, SSEMessage)
    
    # Verify all fields are set correctly
    assert sse_message.data == test_data
    assert sse_message.event == "test_event"
    assert sse_message.id == "test_id"
    assert sse_message.retry == 1000


if __name__ == "__main__":
    pytest.main([__file__])