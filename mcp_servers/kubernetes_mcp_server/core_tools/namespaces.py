"""
Kubernetes MCP Server - core tools: namespaces

提供命名空间相关只读能力：
- namespaces_list：列出所有命名空间
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

# 共享 FastMCP 实例
from .. import mcp  # type: ignore

# Kubernetes Python 客户端
_K8S_IMPORT_ERROR = None
try:
    from kubernetes import client as k8s_client  # type: ignore
    from kubernetes import config as k8s_config  # type: ignore
except Exception as _e:  # pragma: no cover
    _K8S_IMPORT_ERROR = _e
    k8s_client = None  # type: ignore
    k8s_config = None  # type: ignore


def _ensure_k8s_available() -> None:
    if _K8S_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Kubernetes Python 客户端未安装，请在环境中安装 `kubernetes` 包。"
        )


def _load_kube_config(context: Optional[str] = None) -> k8s_client.ApiClient:
    """
    优先从 kubeconfig 加载；失败时尝试 in-cluster。
    """
    _ensure_k8s_available()
    try:
        if context:
            k8s_config.load_kube_config(context=context)
        else:
            k8s_config.load_kube_config()
    except Exception:
        k8s_config.load_incluster_config()
    return k8s_client.ApiClient()


def _ns_summary(item: Any) -> Dict[str, Any]:
    meta = getattr(item, "metadata", None)
    status = getattr(item, "status", None)
    return {
        "name": getattr(meta, "name", None),
        "phase": getattr(status, "phase", None),
        "labels": dict(getattr(meta, "labels", {}) or {}) if meta else {},
    }


@mcp.tool(description="List all the Kubernetes namespaces in the current cluster")
def namespaces_list(
    context: Optional[str] = Field(
        default=None, description="Kubeconfig context name; defaults to current context"
    ),
) -> List[Dict[str, Any]]:
    api_client = _load_kube_config(context=context)
    core_v1 = k8s_client.CoreV1Api(api_client)
    try:
        ret = core_v1.list_namespace()
    except Exception as e:
        raise RuntimeError(f"列出命名空间失败：{e}") from e
    items = getattr(ret, "items", []) or []
    return [_ns_summary(ns) for ns in items]
