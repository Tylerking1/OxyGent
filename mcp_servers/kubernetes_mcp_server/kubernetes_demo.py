"""
Kubernetes MCP 服务器测试示例

本示例展示如何在 OxyGent 中集成和使用 Kubernetes MCP 服务器。
包含完整的配置、启动和测试流程。

使用前请确保：
1. 已安装所有依赖：pip install -r mcp_servers/kubernetes_mcp_server/requirements.txt
2. 配置了可访问的 Kubernetes 集群
3. 设置了正确的环境变量
"""

import asyncio
import os
import sys
import logging
from pathlib import Path

# 添加项目根路径到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from oxygent import MAS, Config, oxy

# 启用调试日志（可选）
logging.basicConfig(level=logging.INFO)

# 配置 LLM
Config.set_agent_llm_model("default_llm")

oxy_space = [
    # LLM 配置
    oxy.HttpLLM(
        name="default_llm",
        api_key=os.getenv("DEFAULT_LLM_API_KEY"),
        base_url=os.getenv("DEFAULT_LLM_BASE_URL"),
        model_name=os.getenv("DEFAULT_LLM_MODEL_NAME"),
        llm_params={"temperature": 0.01},
        semaphore=4,
        timeout=240,
    ),
    # Kubernetes MCP 客户端 - 完整功能模式
    oxy.StdioMCPClient(
        name="kubernetes_mcp_server_tools",
        params={
            "command": "python",
            "args": [
                "-m",
                "mcp_servers.kubernetes_mcp_server.server",
                "--transport",
                "stdio",
                "--toolsets",
                "config,core,helm",
            ],
            "env": {
                "PYTHONPATH": ".",
                "K8S_MCP_TRANSPORT": "stdio",
                "K8S_MCP_TOOLSETS": "config,core,helm",
                "K8S_MCP_READ_ONLY": "false",
                "K8S_MCP_DISABLE_DESTRUCTIVE": "false",
            },
        },
    ),
    # Kubernetes 管理智能体
    oxy.ReActAgent(
        name="k8s_admin_agent",
        desc="Kubernetes 集群管理专家，能够查看和管理 K8s 资源，包括 Pods、Nodes、Namespaces 等",
        is_master=True,
        tools=["kubernetes_mcp_server_tools"],
        trust_mode=False,
        timeout=120,
    ),
]


async def main():
    """启动 Kubernetes MCP 测试示例"""
    async with MAS(oxy_space=oxy_space) as mas:
        await mas.start_web_service(
            first_query="请帮我查看当前 Kubernetes 集群的基本信息",
            welcome_message="""🚀 欢迎使用 Kubernetes 集群管理助手！

我可以帮您完成以下任务：

📋 **集群配置管理**
- 查看 kubeconfig 配置和上下文
- 切换不同的集群上下文

🔍 **资源查看与监控**
- 列出和查看 Pods、Nodes、Namespaces
- 获取资源详细信息和状态
- 查看 Pod 日志和执行命令
- 监控资源使用情况

⚙️ **应用部署管理**
- 使用 Helm 模板部署应用
- 管理应用的生命周期
- 批量操作资源

🛡️ **安全与权限**
- 支持只读模式和安全操作
- 细粒度权限控制

**示例查询：**
- "显示所有命名空间"
- "列出 default 命名空间中的 Pods"
- "查看集群节点状态"
- "获取 kube-system 中某个 Pod 的日志"
- "使用模板部署一个 Nginx 应用"

请告诉我您需要什么帮助！""",
        )


if __name__ == "__main__":
    print("🔧 启动 Kubernetes MCP 服务器测试...")
    print("📝 请确保已配置好环境变量和 Kubernetes 集群访问权限")
    print("🌐 Web 界面将在启动后自动打开")
    print("-" * 50)

    asyncio.run(main())
