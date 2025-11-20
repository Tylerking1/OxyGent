"""
Kubernetes MCP Server package initializer.

提供:
- 全局 FastMCP 实例 (用于在各工具模块上通过 @mcp.tool 装饰器统一注册)
- 非破坏模式与禁删/禁更新等安全开关的环境变量读取
- 其他子模块将通过 `from . import mcp` 共享同一个 MCP 实例
"""

from __future__ import annotations

import os
from mcp.server.fastmcp import FastMCP

# 全局 MCP 实例：各工具模块通过 `from . import mcp` 引用此实例并注册工具
# 运行传输模式由启动入口 server.py 控制 (stdio / sse / streamable-http)
mcp = FastMCP()

# 安全与变更开关（环境变量控制）
# - K8S_MCP_READ_ONLY=true: 仅允许只读/非破坏工具
# - K8S_MCP_DISABLE_DESTRUCTIVE=true: 禁止 destructive 类操作（delete / update 等）
#   注意：这两个开关的生效逻辑由 server.py 的工具过滤器与具体工具内部的保护共同保证
_READ_ONLY = os.getenv("K8S_MCP_READ_ONLY", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_DISABLE_DESTRUCTIVE = os.getenv("K8S_MCP_DISABLE_DESTRUCTIVE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def is_read_only() -> bool:
    """
    返回是否启用只读模式（READ-ONLY）。
    该模式通常会移除 delete/update 等破坏性工具，仅保留只读与创建/更新安全工具的最小集合。
    """
    return _READ_ONLY


def is_disable_destructive() -> bool:
    """
    返回是否禁用破坏性操作（DELETE/UPDATE 等）。
    在 READ-ONLY 未开启时，也可通过该开关细粒度限制工具集合。
    """
    return _DISABLE_DESTRUCTIVE


__all__ = [
    "mcp",
    "is_read_only",
    "is_disable_destructive",
]
