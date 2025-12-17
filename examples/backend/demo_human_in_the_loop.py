import asyncio
import os

from oxygent import MAS, OxyRequest, oxy


async def workflow(oxy_request: OxyRequest):
    # 发消息
    await oxy_request.send_message({"type": "msg_type", "content": "msg_content"})

    # 监听数据流，channel_id 默认是 trace_id
    feedbacks = []
    async for data in oxy_request.get_feedback_stream():
        print(data)
        feedbacks.append(data)
    """requests.post(url="http://127.0.0.1:8080/feedback", json={"channel_id": "xxx", "data": ""})"""

    return ",".join(feedbacks)


oxy_space = [
    oxy.HttpLLM(
        name="default_llm",
        api_key=os.getenv("DEFAULT_LLM_API_KEY"),
        base_url=os.getenv("DEFAULT_LLM_BASE_URL"),
        model_name=os.getenv("DEFAULT_LLM_MODEL_NAME"),
    ),
    oxy.WorkflowAgent(
        name="master_agent",
        func_workflow=workflow,
    ),
]


async def main():
    async with MAS(oxy_space=oxy_space) as mas:
        await mas.start_web_service(first_query="hello")


if __name__ == "__main__":
    asyncio.run(main())
