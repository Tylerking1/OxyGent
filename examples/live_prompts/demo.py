import asyncio
import os

from oxygent import MAS, Config, oxy, preset_tools

Config.set_agent_llm_model("default_llm")


oxy_space = [
    oxy.HttpLLM(
        name="default_llm",
        api_key=os.getenv("DEFAULT_LLM_API_KEY"),
        base_url=os.getenv("DEFAULT_LLM_BASE_URL"),
        model_name=os.getenv("DEFAULT_LLM_MODEL_NAME"),
    ),
    preset_tools.time_tools,
    # 使用系统默认提示词
    oxy.ReActAgent(
        name="time_agent",
        desc="A tool that can query the time",
        prompt="You are a time management assistant. Help users with time-related queries.",
        tools=["time_tools"],
        use_live_prompt=False  # 关闭动态提示词，且prompt为空，则使用系统默认提示词
    ),
    preset_tools.file_tools,

    # 只使用代码中的提示词
    oxy.ReActAgent(
        name="file_agent",
        desc="A tool that can operate the file system",
        tools=["file_tools"],
        prompt="You are a file system assistant. Help users with file operations safely and efficiently.",
        use_live_prompt=False # 关闭动态提示词，则使用代码中的 prompt 参数
    ),
    preset_tools.math_tools,

    # 使用 动态提示词
    oxy.ReActAgent(
        name="math_agent",
        desc="A tool that can perform mathematical calculations.",
        tools=["math_tools"],
        prompt="You are a math assistant. Help users with mathematical calculations.",
    ),
     # 使用 动态提示词
    oxy.ReActAgent(
        is_master=True,
        name="master_agent",
        sub_agents=["time_agent", "file_agent", "math_agent"],
        prompt="You are the master agent. Coordinate the actions of your sub-agents effectively.",
    ),
]


async def main():#
    async with MAS(oxy_space=oxy_space) as mas:
        await mas.start_web_service(
            first_query="What time is it now? Please save it into time.txt."
        )


if __name__ == "__main__":
    asyncio.run(main())
