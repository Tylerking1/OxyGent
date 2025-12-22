# 如何使用动态提示词（Live Prompts）

OxyGent 提供了动态提示词功能，允许您在运行时动态加载和更新智能体的提示词，无需重启应用程序。这个功能特别适用于需要频繁调整提示词或在生产环境中进行 A/B 测试的场景。

## 什么是动态提示词

动态提示词（Live Prompts）是一个存储在数据库中的提示词管理系统，支持：
- **实时更新**：在运行时修改提示词，无需重启应用
- **版本管理**：保存提示词的历史版本，支持回滚
- **热重载**：提示词修改后立即生效
- **备用机制**：当动态提示词不可用时，自动使用默认提示词

## 基本用法

### 1. 导入动态提示词功能

```python
from oxygent.live_prompt import get_live_prompts
```

### 2. 在智能体中使用动态提示词

```python
oxy.ReActAgent(
    name="time_agent",
    desc="A tool that can query the time",
    prompt=get_live_prompts(
        "time_agent_prompt",  # 提示词键名
        "You are a time management assistant. Help users with time-related queries."  # 默认提示词
    ),
    tools=["time_tools"],
)
```

## 函数参数说明

`get_live_prompts(prompt_key: str, default_prompt: Optional[str] = None) -> str`

**参数：**
- `prompt_key` (str): 提示词的唯一标识符，用于从存储中检索提示词
- `default_prompt` (Optional[str]): 默认提示词，当动态提示词不存在或不可用时使用

**工作逻辑：**
1. 首先尝试从存储系统中使用 `prompt_key` 解析提示词
2. 如果未找到且提供了 `default_prompt`，则使用默认提示词
3. 如果未找到且 `default_prompt` 为 None 或空，则返回空字符串

## 完整示例

以下是一个完整的使用动态提示词的示例：

```python
import asyncio
import os

from oxygent import MAS, Config, oxy, preset_tools
from oxygent.live_prompt import get_live_prompts

Config.set_agent_llm_model("default_llm")

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
            "You are a time management assistant. Help users with time-related queries."
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
            "You are a file system assistant. Help users with file operations safely and efficiently."
        )
    ),
    preset_tools.math_tools,
    oxy.ReActAgent(
        name="math_agent",
        desc="A tool that can perform mathematical calculations.",
        tools=["math_tools"],
        prompt=get_live_prompts(
            "math_agent_prompt"  # 没有默认提示词，如果不存在将返回空字符串
        ),
    ),
    oxy.ReActAgent(
        is_master=True,
        name="master_agent",
        sub_agents=["time_agent", "file_agent", "math_agent"],
        prompt=get_live_prompts(
            "master_agent_prompt",
            ""  # 空字符串作为默认值，将使用系统默认提示词
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
```

## 使用场景

### 1. 生产环境优化
在生产环境中，您可以通过 Web 界面实时调整提示词，优化智能体的表现，无需重启服务。

### 2. A/B 测试
通过动态切换不同版本的提示词，可以快速进行 A/B 测试，比较不同提示词的效果。

### 3. 多语言支持
根据用户的语言偏好，动态加载对应语言的提示词。

### 4. 渐进式优化
在开发过程中，可以先使用默认提示词启动系统，然后逐步添加和优化动态提示词。

## 最佳实践

### 1. 提供有意义的默认提示词
```python
prompt=get_live_prompts(
    "customer_service_prompt",
    "You are a helpful customer service assistant. Be polite and professional."
)
```

### 2. 使用描述性的键名
```python
# 好的做法
prompt=get_live_prompts("email_summarizer_prompt", default_prompt)

# 避免的做法
prompt=get_live_prompts("prompt1", default_prompt)
```

### 3. 处理空提示词情况
```python
# 对于可选的提示词，可以不提供默认值
prompt=get_live_prompts("optional_enhancement_prompt")
```

## 配置要求

动态提示词功能需要配置数据库连接：
- 支持 Elasticsearch 作为主要存储
- 当 ES 不可用时，自动回退到 LocalEs（本地存储）
- 通过 `Config` 系统配置数据库连接参数

## 注意事项

1. **性能考虑**：动态提示词会在首次使用时从数据库加载，后续会使用缓存
2. **错误处理**：当动态提示词系统不可用时，会自动使用默认提示词，确保系统稳定运行
3. **版本管理**：系统会自动保存提示词的修改历史，支持版本回滚

通过动态提示词功能，您可以构建更加灵活和可维护的智能体系统，在不影响系统稳定性的前提下，持续优化智能体的表现。

[上一章：选择智能体种类](./1_4_select_agent.md)
[下一章：注册单个智能体](./1_register_single_agent.md)
[回到首页](./readme.md)