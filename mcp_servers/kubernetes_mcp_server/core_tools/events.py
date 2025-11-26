"""
Kubernetes MCP Server - core tools: events

提供 Kubernetes 事件的只读能力：
- events_list：列出所有命名空间或指定命名空间的事件
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


def _event_summary(it: Any) -> Dict[str, Any]:
    meta = getattr(it, "metadata", None)
    involved = getattr(it, "involved_object", None)
    return {
        "name": getattr(meta, "name", None),
        "namespace": getattr(meta, "namespace", None),
        "type": getattr(it, "type", None),
        "reason": getattr(it, "reason", None),
        "message": getattr(it, "message", None),
        "count": getattr(it, "count", None),
        "firstTimestamp": getattr(it, "first_timestamp", None).isoformat()
        if getattr(it, "first_timestamp", None)
        else None,
        "lastTimestamp": getattr(it, "last_timestamp", None).isoformat()
        if getattr(it, "last_timestamp", None)
        else None,
        "involvedObject": {
            "kind": getattr(involved, "kind", None) if involved else None,
            "name": getattr(involved, "name", None) if involved else None,
            "namespace": getattr(involved, "namespace", None) if involved else None,
        },
    }


@mcp.tool(
    description="List Kubernetes events in all namespaces or a specific namespace"
)
def events_list(
    namespace: Optional[str] = Field(
        default=None, description="Optional namespace to list events from"
    ),
    context: Optional[str] = Field(
        default=None, description="Kubeconfig context name; defaults to current context"
    ),
) -> List[Dict[str, Any]]:
    """
    返回按时间顺序的事件摘要列表。
    """
    api_client = _load_kube_config(context=context)
    core_v1 = k8s_client.CoreV1Api(api_client)

    try:
        if namespace:
            ret = core_v1.list_namespaced_event(namespace=namespace)
        else:
            ret = core_v1.list_event_for_all_namespaces()
    except Exception as e:
        raise RuntimeError(f"列出事件失败：{e}") from e

    items = getattr(ret, "items", []) or []
    return [_event_summary(ev) for ev in items]
