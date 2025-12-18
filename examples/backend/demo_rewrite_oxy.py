import asyncio
import os

import httpx

from oxygent import MAS, OxyRequest, OxyResponse, OxyState, oxy


class MyHttpLLM(oxy.HttpLLM):
    async def _execute(self, oxy_request: OxyRequest) -> OxyResponse:
        headers = {"Content-Type": "application/json"}
        headers.update(self.headers(oxy_request))

        payload = {
            "messages": await self._get_messages(oxy_request),
            "model": self.model_name,
        }
        for k, v in self.llm_params.items():
            payload[k] = v
        for k, v in oxy_request.arguments.items():
            if k == "messages":
                continue
            payload[k] = v

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            http_response = await client.post(
                self.base_url, headers=headers, json=payload
            )
            http_response.raise_for_status()
            data = http_response.json()
            response_message = data["choices"][0]["message"]
            result = response_message.get("content")
            return OxyResponse(state=OxyState.COMPLETED, output=result)


oxy_space = [
    MyHttpLLM(
        name="default_llm",
        api_key=os.getenv("DEFAULT_LLM_API_KEY"),
        base_url=os.getenv("DEFAULT_LLM_BASE_URL"),
        model_name=os.getenv("DEFAULT_LLM_MODEL_NAME"),
    ),
]


async def main():
    async with MAS(oxy_space=oxy_space) as mas:
        await mas.call(
            callee="default_llm",
            arguments={
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "hello"},
                ],
                "llm_params": {"temperature": 0.2},
            },
        )


if __name__ == "__main__":
    asyncio.run(main())
