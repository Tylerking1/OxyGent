import asyncio
from typing import Callable

from pydantic import Field

from ...schemas import OxyRequest, OxyResponse, OxyState
from .base_llm import BaseLLM


class MockLLM(BaseLLM):
    func_mock_process: Callable = Field(
        None, exclude=True, description="Mock processing function"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if self.func_mock_process is None:
            self.func_mock_process = self._mock_process

    async def _mock_process(self, oxy_request: OxyRequest):
        await asyncio.sleep(1)
        return "output"

    async def _execute(self, oxy_request: OxyRequest) -> OxyResponse:
        output = await self.func_mock_process(oxy_request)
        return OxyResponse(state=OxyState.COMPLETED, output=output)
