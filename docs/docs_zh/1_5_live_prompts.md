# 如何使用动态提示词（Live Prompts）

OxyGent 提供了动态提示词功能，允许您在运行时动态加载和更新智能体的提示词，无需重启应用程序，适用于需要频繁调整提示词的场景。

## 什么是动态提示词

动态提示词（Live Prompts）是一个存储在数据库中的提示词管理系统，支持：
- **自动集成**：LocalAgent 内置支持，无需额外配置
- **版本管理**：保存提示词的历史版本，支持回滚
- **备用机制**：当动态提示词不可用时，自动使用代码中的默认提示词
- **灵活开关**：可选择启用或禁用 live prompt 功能

## 基本用法

### 方式 1: 默认用法（推荐）

直接在 Agent 中设置 `prompt` 参数，系统会自动使用 live prompt 功能：

```python
oxy.ReActAgent(
    name="time_agent",
    desc="A tool that can query the time",
    prompt="You are a time management assistant. Help users with time-related queries.",
    tools=["time_tools"],
    # use_live_prompt=True 是默认值，可以省略
)
```

**工作原理：**
1. Agent 初始化时，自动从存储中查找键为 `time_agent_prompt` 的 live prompt
2. 如果找到且激活，使用存储中的提示词
3. 如果未找到，使用代码中的 `prompt` 参数作为后备

### 方式 2: 自定义 prompt_key

如果想使用不同的键名：

```python
oxy.ReActAgent(
    name="time_agent",
    desc="A tool that can query the time",
    prompt="Default prompt",
    prompt_key="my_custom_prompt_key",  # 自定义键名
    tools=["time_tools"],
)
```

### 方式 3: 禁用 Live Prompt

如果不需要动态提示词功能（仅使用静态提示词）：

```python
oxy.ReActAgent(
    name="time_agent",
    desc="A tool that can query the time",
    prompt="You are a time management assistant.",
    tools=["time_tools"],
    use_live_prompt=False  # 禁用 live prompt
)
```

## 参数说明

### LocalAgent 的 Live Prompt 相关参数

- **`prompt`** (str): 提示词内容，作为后备使用
- **`prompt_key`** (str, 可选): Live prompt 的键名
  - 默认值: `"{agent_name}_prompt"`
  - 用于从存储中查找动态提示词
- **`use_live_prompt`** (bool, 可选): 是否启用 live prompt 功能
  - 默认值: `True`
  - 设为 `False` 时只使用代码中的 `prompt` 参数

## 完整示例

以下是一个完整的使用动态提示词的示例：

```python
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

async def main():
    async with MAS(oxy_space=oxy_space) as mas:
        await mas.start_web_service(
            first_query="What time is it now? Please save it into time.txt."
        )

if __name__ == "__main__":
    asyncio.run(main())
```

## 热更新提示词

修改存储中的提示词后，需要手动触发热更新才能生效：

### 方法 1: 通过 Agent 实例

```python
# 获取 agent 实例
agent = mas.oxy_name_to_oxy["time_agent"]

# 热更新提示词
success = await agent.reload_prompt()
if success:
    print("提示词已更新")
```

### 方法 2: 通过便捷函数

```python
from oxygent.live_prompt.wrapper import (
    hot_reload_agent,       # 按 agent 名称更新
    hot_reload_prompt,      # 按 prompt_key 更新
    hot_reload_all_prompts  # 更新所有 agents
)

# 热更新单个 agent
await hot_reload_agent("time_agent")

# 热更新使用指定 prompt_key 的所有 agents
await hot_reload_prompt("time_agent_prompt")

# 热更新所有 agents
await hot_reload_all_prompts()
```

### 方法 3: 在保存时自动触发（推荐）

在提示词管理平台的保存 API 中自动触发热更新：

```python
from oxygent.live_prompt.manager import PromptManager
from oxygent.live_prompt.wrapper import hot_reload_prompt

# 保存提示词
await manager.save_prompt(
    prompt_key="time_agent_prompt",
    prompt_content="Updated prompt content..."
)

# 自动触发热更新
await hot_reload_prompt("time_agent_prompt")
```

## 配置要求

动态提示词功能需要配置数据库连接：
- 支持 Elasticsearch 作为主要存储
- 当 ES 不可用时，自动回退到 LocalEs（本地文件存储）
- 通过 `Config` 系统配置数据库连接参数


## 注意事项

1. **向后兼容**：现有代码无需修改，默认启用 live prompt 功能
2. **性能考虑**：
   - 提示词在初始化时从数据库加载一次，之后使用缓存
   - 禁用 live prompt 的 Agent 性能略好（不查询数据库）
3. **错误处理**：当 live prompt 系统不可用时，自动使用代码中的 `prompt` 参数，确保系统稳定运行
4. **版本管理**：系统会自动保存提示词的修改历史，支持版本回滚
5. **灵活控制**：可以为每个 Agent 单独设置是否启用 live prompt

## 常见问题

### Q1: 如何禁用 live prompt 功能？
**A**: 设置 `use_live_prompt=False` 参数。

### Q2: prompt_key 的默认值是什么？
**A**: `{agent_name}_prompt`，例如 Agent 名为 `time_agent`，则默认 `prompt_key` 为 `time_agent_prompt`。

### Q3: 如果存储中没有提示词会怎样？
**A**: 会使用代码中的 `prompt` 参数作为后备。

### Q4: live prompt 会影响性能吗？
**A**: 影响很小。只在初始化时访问一次数据库，之后使用缓存。如有极高性能要求，可禁用 live prompt。

## 相关文档

- [Live Prompts 集成指南](./live_prompts_integration.md) - 详细的集成说明
- [Live Prompts 热更新指南](./live_prompts_hot_reload.md) - 热更新使用方法
- [use_live_prompt 开关参考](./use_live_prompt_reference.md) - 开关参数详解

[上一章：选择智能体种类](./1_4_select_agent.md)
[下一章：注册单个智能体](./1_register_single_agent.md)
[回到首页](./readme.md)