"""
Kubernetes MCP Server - core tools package

按功能拆分的核心工具集合：
- pods.py：Pods 相关 list/get/logs 等只读与基础能力
- resources.py：通用资源 list/get/create_or_update/delete
- events.py：事件列表
- namespaces.py：命名空间列表
- nodes.py：节点 top/stats/logs

说明：
- 具体工具在子模块中通过 `from .. import mcp` 注册到全局 MCP 实例。
- 服务器入口会按 `--toolsets` 与安全开关（只读/禁破坏）选择性导入子模块。
"""

from __future__ import annotations

__all__ = []
