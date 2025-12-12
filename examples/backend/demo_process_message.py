import asyncio
import os

from oxygent import MAS, Config, OxyRequest, oxy

Config.set_message_is_show_in_terminal(True)


def process_message(dict_message: dict, oxy_request: OxyRequest) -> dict:
    if dict_message["data"]["type"] == "stream":
        dict_message["data"]["content"]["delta"] += "-"
    return dict_message


oxy_space = [
    oxy.HttpLLM(
        name="default_llm",
        api_key=os.getenv("DEFAULT_LLM_API_KEY"),
        base_url=os.getenv("DEFAULT_LLM_BASE_URL"),
        model_name=os.getenv("DEFAULT_LLM_MODEL_NAME"),
        llm_params={"stream": True},
    ),
    oxy.ChatAgent(
        name="qa_agent",
        llm_model="default_llm",
    ),
]


async def main():
    async with MAS(oxy_space=oxy_space, func_process_message=process_message) as mas:
        await mas.start_web_service(first_query="hello")


if __name__ == "__main__":
    asyncio.run(main())
