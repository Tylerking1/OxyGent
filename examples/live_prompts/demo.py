import asyncio
import os

from oxygent import MAS, Config, oxy, preset_tools
from oxygent.live_prompt import get_live_prompts

Config.set_agent_llm_model("default_llm")

"""
get_live_prompts(prompt_key: str, default_prompt: Optional[str] = None) -> str
Logic:
1. First try to resolve from storage using prompt_key
2. If not found and default_prompt is provided, use default_prompt
3. If not found and default_prompt is None/empty, return "" 
"""

oxy_space = [
    oxy.HttpLLM(
        name="default_llm",
        api_key=os.getenv("DEFAULT_LLM_API_KEY"),
        base_url=os.getenv("DEFAULT_LLM_BASE_URL"),
        model_name=os.getenv("DEFAULT_LLM_MODEL_NAME"),
    ),
    preset_tools.time_tools,
    oxy.ReActAgent(
        name="time_agent",
        desc="A tool that can query the time",
        prompt=get_live_prompts(
            "time_agent_prompt",
            "You are a time management assistant. Help users with time-related queries."  # default prompt
        ),
        tools=["time_tools"],
    ),
    preset_tools.file_tools,

    oxy.ReActAgent(
        name="file_agent",
        desc="A tool that can operate the file system",
        tools=["file_tools"],
        prompt=get_live_prompts(
            "file_agent_prompt",
            "You are a file system assistant. Help users with file operations safely and efficiently."  # default prompt
        )
    ),
    preset_tools.math_tools,
    oxy.ReActAgent(
        name="math_agent",
        desc="A tool that can perform mathematical calculations.",
        tools=["math_tools"],
        prompt=get_live_prompts(
            "math_agent_prompt"
        ),
    ),
    oxy.ReActAgent(
        is_master=True,
        name="master_agent",
        sub_agents=["time_agent", "file_agent", "math_agent"],
        prompt=get_live_prompts(
            "master_agent_prompt", # prompt key
            ""  # can be empty use system default
        ),
    ),
]


async def main():
    async with MAS(oxy_space=oxy_space) as mas:
        await mas.start_web_service(
            first_query="What time is it now? Please save it into time.txt."
        )


if __name__ == "__main__":
    asyncio.run(main())
