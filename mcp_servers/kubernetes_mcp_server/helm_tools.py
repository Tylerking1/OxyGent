"""
Kubernetes MCP Server - helm tools (template-first approach)

提供无需 Helm 二进制的模板化能力：
- helm_template_apply：使用 Jinja2 渲染 Helm 风格模板（或通用 YAML 模板），将生成的多文档 YAML 逐条 Create/Patch 到集群
- helm_template_uninstall：使用同一模板与 values 渲染出目标对象，逐条 Delete
- 说明：此方案以“渲染→K8s 统一资源 API”的流程替代直接调用 Helm CLI，规避二进制依赖与环境不一致问题

注意：
- 属于写/删除操作，受只读与禁破坏开关保护
- 多集群支持：可选 context 参数；默认使用当前 kubeconfig 上下文或 in-cluster 配置
- 模板渲染输入：`template`（字符串，支持 Jinja2 语法）；`values`（字典）
- 多文档 YAML：使用 `---` 分隔；每个文档需包含 apiVersion/kind/metadata.name 顶级字段
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from pydantic import Field

# 共享 MCP 实例与安全开关
from . import mcp, is_read_only, is_disable_destructive  # type: ignore

# 依赖：Kubernetes Python 客户端（包含 dynamic）
_K8S_IMPORT_ERROR = None
try:
    from kubernetes import client as k8s_client  # type: ignore
    from kubernetes import config as k8s_config  # type: ignore
    from kubernetes.dynamic import DynamicClient  # type: ignore
except Exception as _e:  # pragma: no cover
    _K8S_IMPORT_ERROR = _e
    k8s_client = None  # type: ignore
    k8s_config = None  # type: ignore
    DynamicClient = None  # type: ignore

# 解析与模板：PyYAML + Jinja2
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

try:
    from jinja2 import Environment, StrictUndefined  # type: ignore
except Exception:  # pragma: no cover
    Environment = None  # type: ignore
    StrictUndefined = None  # type: ignore


def _ensure_k8s_available() -> None:
    if _K8S_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Kubernetes Python 客户端未安装，请在环境中安装 `kubernetes` 包。"
        )


def _ensure_template_engine() -> None:
    if Environment is None or StrictUndefined is None:
        raise RuntimeError("Jinja2 未安装，请在环境中安装 `Jinja2` 包。")
    if yaml is None:
        raise RuntimeError("PyYAML 未安装，请在环境中安装 `PyYAML` 包。")


def _api_dyn(context: Optional[str]) -> DynamicClient:
    """
    返回 DynamicClient；优先 kubeconfig，其次 in-cluster。
    """
    _ensure_k8s_available()
    try:
        if context:
            k8s_config.load_kube_config(context=context)
        else:
            k8s_config.load_kube_config()
    except Exception:
        k8s_config.load_incluster_config()
    api_client = k8s_client.ApiClient()
    return DynamicClient(api_client)  # type: ignore


def _get_resource(dyn: DynamicClient, apiVersion: str, kind: str):
    """
    解析并返回动态资源对象；异常统一抛出。
    """
    try:
        return dyn.resources.get(api_version=apiVersion, kind=kind)
    except Exception as e:
        raise RuntimeError(
            f"无法解析资源类型（apiVersion={apiVersion}, kind={kind}）：{e}"
        ) from e


def _sanitize(obj: Any) -> Dict[str, Any]:
    """
    将任意 Kubernetes 对象转为字典；DynamicClient 返回已是字典，保持幂等。
    """
    if isinstance(obj, dict):
        return obj
    try:
        ac = k8s_client.ApiClient()
        return ac.sanitize_for_serialization(obj)  # type: ignore
    except Exception:
        return json.loads(json.dumps(obj, default=str))


def _mask_secret(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    对 Secret 对象进行敏感字段掩码处理：data/stringData 的值统一替换为 "***"。
    非 Secret 对象原样返回。
    """
    try:
        if not isinstance(obj, dict):
            return obj
        if obj.get("kind") != "Secret":
            return obj
        if isinstance(obj.get("data"), dict):
            obj["data"] = {k: "***" for k in obj["data"].keys()}
        if isinstance(obj.get("stringData"), dict):
            obj["stringData"] = {k: "***" for k in obj["stringData"].keys()}
    except Exception:
        return obj
    return obj


def _render_to_documents(template: str, values: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    使用 Jinja2 渲染模板，解析为多 YAML 文档对象列表。
    文档需包含 apiVersion/kind/metadata.name 顶级字段。
    """
    _ensure_template_engine()
    try:
        env = Environment(
            undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True
        )
        text = env.from_string(template).render(**(values or {}))
    except Exception as e:
        raise RuntimeError(f"模板渲染失败：{e}") from e

    docs: List[Dict[str, Any]] = []
    try:
        for doc in yaml.safe_load_all(text):  # type: ignore
            if not doc:
                continue
            if not isinstance(doc, dict):
                raise RuntimeError("渲染结果中的某些文档不是对象字典")
            # 基本字段校验
            if not doc.get("apiVersion") or not doc.get("kind"):
                raise RuntimeError("渲染文档缺少 apiVersion/kind")
            meta = doc.get("metadata") or {}
            if not meta.get("name"):
                raise RuntimeError("渲染文档缺少 metadata.name")
            docs.append(doc)
    except Exception as e:
        raise RuntimeError(f"多文档 YAML 解析失败：{e}") from e
    return docs


def _create_or_patch(
    dyn: DynamicClient, obj: Dict[str, Any], default_namespace: Optional[str]
) -> Dict[str, Any]:
    """
    对单个对象：若存在则 merge-patch，不存在则 create。
    """
    apiVersion = obj.get("apiVersion")
    kind = obj.get("kind")
    meta = obj.get("metadata") or {}
    name = meta.get("name")
    ns = meta.get("namespace") or default_namespace

    res = _get_resource(dyn, apiVersion, kind)

    # 判存
    exists = None
    try:
        exists = res.get(name=name, namespace=ns) if ns else res.get(name=name)
    except Exception:
        exists = None

    if exists:
        patched = (
            res.patch(
                name=name,
                namespace=ns,
                body=obj,
                content_type="application/merge-patch+json",
            )
            if ns
            else res.patch(
                name=name,
                body=obj,
                content_type="application/merge-patch+json",
            )
        )
        return _mask_secret(
            patched if isinstance(patched, dict) else _sanitize(patched)
        )
    else:
        created = (
            res.create(
                body=obj,
                namespace=ns,
            )
            if ns
            else res.create(body=obj)
        )
        return _mask_secret(
            created if isinstance(created, dict) else _sanitize(created)
        )


def _delete(
    dyn: DynamicClient, obj: Dict[str, Any], default_namespace: Optional[str]
) -> Dict[str, Any]:
    """
    删除单个对象：按 apiVersion/kind/name/namespace。
    """
    apiVersion = obj.get("apiVersion")
    kind = obj.get("kind")
    meta = obj.get("metadata") or {}
    name = meta.get("name")
    ns = meta.get("namespace") or default_namespace

    res = _get_resource(dyn, apiVersion, kind)
    deleted = res.delete(name=name, namespace=ns) if ns else res.delete(name=name)
    return _mask_secret(deleted if isinstance(deleted, dict) else _sanitize(deleted))


@mcp.tool(
    description="Render template with values and apply resources to the cluster (create or patch)"
)
def helm_template_apply(
    template: str = Field(
        description="Jinja2 模板字符串（支持多文档 YAML，通过 '---' 分隔）"
    ),
    values: Dict[str, Any] = Field(
        default_factory=dict, description="模板渲染的变量字典"
    ),
    namespace: Optional[str] = Field(
        default=None,
        description="默认命名空间（当文档未指定 metadata.namespace 时使用）",
    ),
    context: Optional[str] = Field(
        default=None, description="kubeconfig 上下文；默认当前上下文"
    ),
) -> List[Dict[str, Any]]:
    # 安全保护：只读或禁破坏时拒绝写操作
    if is_read_only() or is_disable_destructive():
        raise RuntimeError("写操作被禁止：当前处于只读或禁破坏模式")

    docs = _render_to_documents(template, values)
    dyn = _api_dyn(context)

    results: List[Dict[str, Any]] = []
    for doc in docs:
        try:
            results.append(_create_or_patch(dyn, doc, namespace))
        except Exception as e:
            raise RuntimeError(
                f"应用资源失败（{doc.get('kind')} {doc.get('metadata', {}).get('name')}）：{e}"
            ) from e
    return results


@mcp.tool(
    description="Render template with values and uninstall rendered resources from the cluster"
)
def helm_template_uninstall(
    template: str = Field(
        description="Jinja2 模板字符串（支持多文档 YAML，通过 '---' 分隔）"
    ),
    values: Dict[str, Any] = Field(
        default_factory=dict, description="模板渲染的变量字典"
    ),
    namespace: Optional[str] = Field(
        default=None,
        description="默认命名空间（当文档未指定 metadata.namespace 时使用）",
    ),
    context: Optional[str] = Field(
        default=None, description="kubeconfig 上下文；默认当前上下文"
    ),
) -> List[Dict[str, Any]]:
    # 安全保护：只读或禁破坏时拒绝删除
    if is_read_only() or is_disable_destructive():
        raise RuntimeError("删除操作被禁止：当前处于只读或禁破坏模式")

    docs = _render_to_documents(template, values)
    dyn = _api_dyn(context)

    results: List[Dict[str, Any]] = []
    for doc in docs:
        try:
            results.append(_delete(dyn, doc, namespace))
        except Exception as e:
            raise RuntimeError(
                f"卸载资源失败（{doc.get('kind')} {doc.get('metadata', {}).get('name')}）：{e}"
            ) from e
    return results
