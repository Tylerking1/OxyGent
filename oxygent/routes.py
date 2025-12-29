"""routes.py.

FastAPI routing layer for the OxyGent MAS service.

This module exposes several HTTP endpoints that support:
    * Health checks and root redirection
    * Retrieval of node‐level execution details stored in Elasticsearch
    * Proxying user requests to an LLM provider through the OxyGent agent stack
    * Lightweight persistence for scripted calls (save / list / load)
    * Conversation rating and evaluation system

Every public callable is documented using **Google Python Style** docstrings so
that automatic documentation tooling such as *Sphinx napoleon* can render them
cleanly.

Typical usage example::

    # uvicorn main:app --reload
    curl http://localhost:8000/check_alive  #→ {"alive": 1}
"""

import ast
import json
import logging
import os
import re
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any

import aiofiles
from fastapi import APIRouter, File, UploadFile, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .config import Config
from .databases.db_es import JesEs, LocalEs
from .db_factory import DBFactory
from .oxy_factory import OxyFactory, SecurityError
from .schemas import OxyRequest, WebResponse
from .schemas.evaluation import (
    RatingRequest,
    RatingResponse,
    ConversationWithRating,
    RatingStats
)
from .evaluation_manager import EvaluationManager
from .utils.data_utils import add_post_and_child_node_ids

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

async def get_es_client():
    """Get Elasticsearch client based on configuration.

    Returns:
        Elasticsearch client instance (JesEs or LocalEs)
    """
    db_factory = DBFactory()
    if Config.get_es_config():
        jes_config = Config.get_es_config()
        hosts = jes_config["hosts"]
        user = jes_config["user"]
        password = jes_config["password"]
        return db_factory.get_instance(JesEs, hosts, user, password)
    else:
        return db_factory.get_instance(LocalEs)


def cleanResult(s):
    s=s.strip()
    prefix = "```json"
    suffix = "```"
    if s.startswith(prefix):
        s = s[len(prefix):]
    if s.endswith(suffix):
        s = s[:-len(suffix)]
    return s


# Basic route to redirect to the web interface
@router.get("/")
def read_root():
    """Redirect the client to the bundled web front-end.

    Returns:
        fastapi.responses.RedirectResponse: HTTP 307 redirect to
        ``./web/index.html`` that ships with the service UI.
    """
    return RedirectResponse(url="./web/index.html")


@router.get("/check_alive")
def check_alive():
    """Health‑check endpoint.

    Returns:
        dict: ``{"alive": 1}`` when the service is running.
    """
    # Application health check endpoint
    return {"alive": 1}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    upload_dir = os.path.join(Config.get_cache_save_dir(), "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    file_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    file_path = os.path.join(upload_dir, file_name)
    pic_url = f"../static/{file_name}"

    # Save file asynchronously
    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # Return file path
    return WebResponse(data={"file_name": pic_url}).to_dict()


@router.get("/node")
async def get_node_info(item_id: str):
    """Retrieve execution-node details using its *node_id* or *trace_id*.

    Args:
        item_id: Either a node identifier or a trace identifier. If the input
            is a trace-level identifier the function resolves it to the first
            concrete node before returning details.

    Returns:
        dict: A ``WebResponse``-compatible dictionary containing the node
        payload enriched with ``pre_id`` and ``next_id`` navigation helpers.
    """
    es_client = await get_es_client()
    es_response = await es_client.search(
        Config.get_app_name() + "_node", {"query": {"term": {"_id": item_id}}}
    )
    try:
        datas = es_response["hits"]["hits"]
        if datas:
            node_data = datas[0]["_source"]
            trace_id = node_data["trace_id"]
        else:
            # puting item_id as trace_id
            trace_id = item_id

        """Get trace_id from trace table (abandoned)"""
        """If error, get trace_id from node table."""
        es_response = await es_client.search(
            Config.get_app_name() + "_node",
            {
                "query": {"term": {"trace_id": trace_id}},  # all of the nodes
                "size": 10000,
                "sort": [{"create_time": {"order": "asc"}}],
            },
        )
        node_ids = []
        for data in es_response["hits"]["hits"]:
            node_ids.append(data["_source"]["node_id"])

        if len(node_ids) == 0:
            return WebResponse(code=400, message="illegal node_id").to_dict()

        if trace_id == item_id:
            # puting item_id from trace_id，get node_id data for another time
            item_id = node_ids[0]
            es_response = await es_client.search(
                Config.get_app_name() + "_node", {"query": {"term": {"_id": item_id}}}
            )
            datas = es_response["hits"]["hits"]
            node_data = datas[0]["_source"]

        for i, node_id in enumerate(node_ids):
            if item_id == node_id:
                node_data["pre_id"] = node_ids[i - 1] if i >= 1 else ""
                node_data["next_id"] = node_ids[i + 1] if i <= len(node_ids) - 2 else ""

                if "input" in node_data:
                    node_data["input"] = json.loads(node_data["input"])

                if "prompt" in node_data["input"]["class_attr"]:
                    del node_data["input"]["class_attr"]["prompt"]
                env_value_to_key = {v: k for k, v in os.environ.items()}

                # Generate the maximum and minimum values for the data range
                node_data["data_range_map"] = dict()
                for tree in [
                    node_data["input"]["class_attr"],
                    node_data["input"]["class_attr"].get("llm_params", dict()),
                    node_data["input"]["arguments"],
                ]:
                    for k, v in tree.items():
                        if v and isinstance(v, str) and v in env_value_to_key:
                            tree[k] = f"${{{env_value_to_key[v]}}}"
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            if v <= 1:
                                max_value = 1
                            else:
                                max_value = v * 10
                            node_data["data_range_map"][k] = {
                                "min": 0,
                                "max": max_value,
                            }
                return WebResponse(data=node_data).to_dict()

    except Exception:
        error_msg = traceback.format_exc()
        logger.error(error_msg)
        return WebResponse(code=500, message="遇到问题").to_dict()


# Define the data model for the LLM call request
@router.get("/view")
async def get_task_info(item_id: str):
    db_factory = DBFactory()
    if Config.get_es_config():
        jes_config = Config.get_es_config()
        hosts = jes_config["hosts"]
        user = jes_config["user"]
        password = jes_config["password"]
        es_client = db_factory.get_instance(JesEs, hosts, user, password)
    else:
        es_client = db_factory.get_instance(LocalEs)

    # es_client.exists(Config.get_app_name() + "_node", doc_id=item_id)

    # If item_id is node_id
    es_response = await es_client.search(
        Config.get_app_name() + "_node", {"query": {"term": {"_id": item_id}}}
    )
    datas = es_response["hits"]["hits"]
    if datas:
        node_data = datas[0]["_source"]
        trace_id = node_data["trace_id"]
    else:
        # Input item_id as trace_id
        trace_id = item_id


    es_response = await es_client.search(
        Config.get_app_name() + "_node",
        {
            "query": {"term": {"trace_id": trace_id}},
            "size": 10000,
            "sort": [{"create_time": {"order": "asc"}}],
        },
    )
    nodes = []
    for data in es_response["hits"]["hits"]:
        data["_source"]["call_stack"] = data["_source"]["call_stack"]
        data["_source"]["node_id_stack"] = data["_source"]["node_id_stack"]
        data["_source"]["pre_node_ids"] = data["_source"]["pre_node_ids"]
        if (
            len(data["_source"]["pre_node_ids"]) == 1
            and data["_source"]["pre_node_ids"][0] == ""
        ):
            data["_source"]["pre_node_ids"] = []
        nodes.append(data["_source"])
    for index, node in enumerate(nodes):
        node["index"] = index
    add_post_and_child_node_ids(nodes)
    task_data = {"nodes": nodes, "trace_id": trace_id}
    return WebResponse(data=task_data).to_dict()


class Item(BaseModel):
    class_attr: dict
    arguments: dict


@router.post("/call")
async def call(item: Item):
    """Invoke an **OxyGent** agent according to the *Item* request.

    The endpoint supports ad-hoc overrides for both class constructor arguments
    (``class_attr`` field) and runtime ``arguments``.

    Example::

        POST /call
        {
            "class_attr": {"class_name": "api_llm", "max_tokens": 2048},
            "arguments": {"temperature": 0.7, "stream": False}
        }

    Args:
        item: The validated request payload.

    Returns:
        dict: ``WebResponse`` wrapper containing the model output.
    """
    try:
        pattern = r"^\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}$"
        for tree in [
            item.class_attr,
            item.class_attr.get("llm_params", dict()),
            item.arguments,
        ]:
            for k, v in tree.items():
                if not isinstance(v, str):
                    continue
                match = re.match(pattern, v.strip())
                if match:
                    tree[k] = os.getenv(match.group(1), v)

        item.class_attr["name"] = item.class_attr["class_name"].lower()
        llm_params_type_dict = {
            "temperature": float,
            "max_tokens": int,
            "top_p": float,
        }
        for k, v in item.class_attr.get("llm_params", dict()).items():
            if k in llm_params_type_dict:
                item.class_attr["llm_params"][k] = llm_params_type_dict[k](v)
        oxy = OxyFactory.create_oxy(item.class_attr["class_name"], **item.class_attr)
        oxy_response = await oxy.execute(OxyRequest(arguments=item.arguments))
        return WebResponse(data={"output": oxy_response.output}).to_dict()
    except Exception:
        error_msg = traceback.format_exc()
        logger.error(error_msg)
        return WebResponse(code=500, message="遇到问题").to_dict()


class Script(BaseModel):
    """Schema for serialized *calling scripts* stored on disk.

    Attributes:
        name: Human-friendly script label displayed in the UI.
        contents: Arbitrary list structure that is later posted to ``/call``.
    """

    name: str
    contents: list


# ---------------------------------------------------------------------------
# Local *script* storage helpers
# ---------------------------------------------------------------------------


@router.get("/list_script")
def list_script():
    script_save_dir = os.path.join(Config.get_cache_save_dir(), "script")
    os.makedirs(script_save_dir, exist_ok=True)
    files = os.listdir(script_save_dir)
    if files:
        return WebResponse(
            data={
                "scripts": [
                    os.path.splitext(file)[0]
                    for file in files
                    if file.endswith(".json")
                ]
            }
        ).to_dict()
    else:
        return WebResponse(data={"scripts": []}).to_dict()


@router.post("/save_script")
def save_script(script: Script):
    """Persist a script definition to ``$CACHE_DIR/script``.

    Args:
        script: The script metadata and payload to store.

    Returns:
        dict: ``WebResponse`` with the generated ``script_id`` timestamp.
    """
    script_save_dir = os.path.join(Config.get_cache_save_dir(), "script")
    with open(os.path.join(script_save_dir, script.name + ".json"), "w") as f:
        f.write(json.dumps(script.contents, ensure_ascii=False))
    return WebResponse(data={"script_id": script.name + ".json"}).to_dict()


@router.get("/load_script")
def load_script(item_id: str):
    """Load a previously saved script.

    Args:
        script_id: Timestamp‑based identifier returned by :func:`save_script`.

    Returns:
        dict: ``WebResponse`` containing the original ``contents`` array or an
        error message when the file is missing.
    """
    script_save_dir = os.path.join(Config.get_cache_save_dir(), "script")

    json_path = os.path.join(script_save_dir, item_id + ".json")
    if not os.path.exists(json_path):
        return WebResponse(code=500, message="File not exist").to_dict()
    with open(json_path, "r") as f:
        return WebResponse(data={"contents": json.loads(f.read())}).to_dict()


# =============================================================================
# Prompt Management API Routes
# =============================================================================

# Prompt management request/response models
class PromptCreateRequest(BaseModel):
    prompt_key: str
    prompt_content: str
    description: str = ""
    category: str = "custom"
    agent_type: str = ""
    is_active: bool = True
    tags: List[str] = []
    created_by: str = "user"


class PromptUpdateRequest(BaseModel):
    prompt_content: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    agent_type: Optional[str] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None


class PromptResponse(BaseModel):
    id: str
    prompt_key: str
    prompt_content: str
    description: str
    category: str
    agent_type: str
    version: int
    created_at: str
    updated_at: str
    created_by: str
    tags: List[str]


class PromptApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None


@router.get("/api/prompts/", response_model=PromptApiResponse)
async def list_prompts(
    category: Optional[str] = Query(None, description="Category filter"),
    agent_type: Optional[str] = Query(None, description="Agent type filter"),
    is_active: Optional[bool] = Query(None, description="Active status filter"),
    tags: Optional[str] = Query(None, description="Tags filter, comma separated")
):
    """List prompts"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        tag_list = tags.split(",") if tags else None

        prompts = await manager.list_prompts(
            category=category,
            agent_type=agent_type,
            is_active=is_active,
            tags=tag_list
        )

        return PromptApiResponse(
            success=True,
            message="Successfully retrieved prompt list",
            data=prompts
        )
    except Exception as e:
        logger.error(f"Failed to list prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/prompts/{prompt_key}", response_model=PromptApiResponse)
async def get_prompt(prompt_key: str):
    """Get single prompt"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        # Use cache to get latest data (cache is updated immediately on save)
        prompt = await manager.get_prompt(prompt_key, use_cache=True)

        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")

        prompt["id"] = prompt_key
        return PromptApiResponse(
            success=True,
            message="Successfully retrieved prompt",
            data=prompt
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/", response_model=PromptApiResponse)
async def create_prompt(request: PromptCreateRequest):
    """Create prompt"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()

        # Check if already exists (use cache for consistency)
        existing = await manager.get_prompt(request.prompt_key, use_cache=True)
        if existing:
            raise HTTPException(status_code=400, detail="Prompt already exists")

        success = await manager.save_prompt(
            prompt_key=request.prompt_key,
            prompt_content=request.prompt_content,
            description=request.description,
            category=request.category,
            agent_type=request.agent_type,
            is_active=request.is_active,
            tags=request.tags,
            created_by=request.created_by
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to create prompt")

        return PromptApiResponse(
            success=True,
            message="Successfully created prompt",
            data={"prompt_key": request.prompt_key}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/prompts/{prompt_key}", response_model=PromptApiResponse)
async def update_prompt(prompt_key: str, request: PromptUpdateRequest):
    """Update prompt"""
    try:
        from .live_prompt import get_prompt_manager, hot_reload_prompt
        manager = await get_prompt_manager()
        
        # Get existing prompt (use cache for cache-first strategy)
        existing = await manager.get_prompt(prompt_key, use_cache=True)
        if not existing:
            raise HTTPException(status_code=404, detail="Prompt not found")

        has_changes = (
            request.prompt_content is not None
            and request.prompt_content != existing.get("prompt_content", "")
        )

        if not has_changes:
            return PromptApiResponse(
                success=False,
                message="No changes detected; update the prompt before saving.",
                data={"prompt_key": prompt_key}
            )

        # Update fields
        update_data = {}
        if request.prompt_content is not None:
            update_data["prompt_content"] = request.prompt_content
        else:
            update_data["prompt_content"] = existing["prompt_content"]

        if request.description is not None:
            update_data["description"] = request.description
        else:
            update_data["description"] = existing.get("description", "")

        if request.category is not None:
            update_data["category"] = request.category
        else:
            update_data["category"] = existing.get("category", "custom")

        if request.agent_type is not None:
            update_data["agent_type"] = request.agent_type
        else:
            update_data["agent_type"] = existing.get("agent_type", "")

        if request.tags is not None:
            update_data["tags"] = request.tags
        else:
            update_data["tags"] = existing.get("tags", [])

        success = await manager.save_prompt(
            prompt_key=prompt_key,
            **update_data,
            is_active=request.is_active if request.is_active is not None else existing.get("is_active", True),
            created_by=existing.get("created_by", "user")
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update prompt")

        hot_reload_success = False
        if request.prompt_content is not None:
            hot_reload_success = await hot_reload_prompt(prompt_key)
        
        return PromptApiResponse(
            success=True,
            message="Successfully updated prompt" + (
                ", auto hot-reloaded to all related agents" if hot_reload_success else ""
            ),
            data={
                "prompt_key": prompt_key,
                "hot_reload_success": hot_reload_success,
                "auto_updated": hot_reload_success
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/prompts/{prompt_key}", response_model=PromptApiResponse)
async def delete_prompt(prompt_key: str):
    """Delete prompt"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        success = await manager.delete_prompt(prompt_key)

        if not success:
            raise HTTPException(status_code=404, detail="Prompt not found")

        return PromptApiResponse(
            success=True,
            message="Successfully deleted prompt",
            data={"prompt_key": prompt_key}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/prompts/search/", response_model=PromptApiResponse)
async def search_prompts(
    keyword: str = Query(..., description="Search keyword"),
    category: Optional[str] = Query(None, description="Category filter")
):
    """Search prompts"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        results = await manager.search_prompts(keyword, category)

        return PromptApiResponse(
            success=True,
            message="Successfully searched prompts",
            data=results
        )
    except Exception as e:
        logger.error(f"Failed to search prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/hot-reload/{prompt_key}", response_model=PromptApiResponse)
async def hot_reload_prompt_by_key(prompt_key: str):
    """Hot reload specified prompt to all related agents"""
    try:
        from .live_prompt import hot_reload_prompt, dynamic_agent_manager

        # Execute hot reload
        success = await hot_reload_prompt(prompt_key)

        if not success:
            return PromptApiResponse(
                success=False,
                message=f"No agents found using prompt {prompt_key} or update failed",
                data={"prompt_key": prompt_key, "updated_agents": []}
            )

        # Get list of updated agents
        agent_mapping = dynamic_agent_manager.get_agent_prompt_mapping()
        updated_agents = [
            agent_name for agent_name, key in agent_mapping.items()
            if key == prompt_key
        ]

        return PromptApiResponse(
            success=True,
            message=f"Successfully hot reloaded prompt {prompt_key}",
            data={
                "prompt_key": prompt_key,
                "updated_agents": updated_agents,
                "reload_time": datetime.now().isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Failed to hot reload prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/hot-reload/agent/{agent_name}", response_model=PromptApiResponse)
async def hot_reload_agent_prompt(agent_name: str):
    """Hot reload prompt for specified agent"""
    try:
        from .live_prompt import hot_reload_agent, dynamic_agent_manager

        success = await hot_reload_agent(agent_name)

        if not success:
            return PromptApiResponse(
                success=False,
                message=f"Agent {agent_name} not found or update failed",
                data={"agent_name": agent_name}
            )

        # Get agent's corresponding prompt key
        agent_mapping = dynamic_agent_manager.get_agent_prompt_mapping()
        prompt_key = agent_mapping.get(agent_name, "unknown")

        return PromptApiResponse(
            success=True,
            message=f"Successfully hot reloaded agent {agent_name}'s prompt",
            data={
                "agent_name": agent_name,
                "prompt_key": prompt_key,
                "reload_time": datetime.now().isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Failed to hot reload agent {agent_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/hot-reload/all", response_model=PromptApiResponse)
async def hot_reload_all_agent_prompts():
    """Hot reload all agent prompts"""
    try:
        from .live_prompt import hot_reload_all_prompts

        results = await hot_reload_all_prompts()

        return PromptApiResponse(
            success=bool(results),
            message="Successfully completed batch hot reload" if results else "No agents to reload",
            data={
                "reload_success": results,
                "reload_time": datetime.now().isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Failed to hot reload all prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Prompt Version Management API Routes
# =============================================================================

@router.get("/api/prompts/{prompt_key}/history", response_model=PromptApiResponse)
async def get_prompt_history(prompt_key: str):
    """Get prompt version history"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        history = await manager.get_prompt_history(prompt_key)

        return PromptApiResponse(
            success=True,
            message="Successfully retrieved prompt history",
            data=history
        )
    except Exception as e:
        logger.error(f"Failed to get prompt history for {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/{prompt_key}/revert/{target_version}", response_model=PromptApiResponse)
async def revert_prompt_to_version(prompt_key: str, target_version: int):
    """Revert prompt to specific version"""
    try:
        from .live_prompt import get_prompt_manager, hot_reload_prompt
        manager = await get_prompt_manager()

        # Check if prompt exists (without cache to ensure fresh check)
        existing = await manager.get_prompt(prompt_key, use_cache=False)
        if not existing:
            raise HTTPException(status_code=404, detail="Prompt not found")

        # Revert to target version
        success = await manager.revert_to_version(prompt_key, target_version)

        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to revert to version {target_version}")

        # Auto hot reload after revert
        hot_reload_success = await hot_reload_prompt(prompt_key)

        return PromptApiResponse(
            success=True,
            message=f"Successfully reverted {prompt_key} to version {target_version}",
            data={
                "prompt_key": prompt_key,
                "reverted_to_version": target_version,
                "hot_reload_success": hot_reload_success,
                "revert_time": datetime.now().isoformat()
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revert prompt {prompt_key} to version {target_version}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/prompts/{prompt_key}/version/{version}", response_model=PromptApiResponse)
async def get_prompt_version(prompt_key: str, version: int):
    """Get specific version of a prompt"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()

        # Get version history
        history = await manager.get_prompt_history(prompt_key)

        # Find the specific version
        target_version = None
        for hist in history:
            if hist.get("version") == version:
                target_version = hist
                break

        if not target_version:
            raise HTTPException(status_code=404, detail=f"Version {version} not found for prompt {prompt_key}")

        return PromptApiResponse(
            success=True,
            message=f"Successfully retrieved version {version} of prompt {prompt_key}",
            data=target_version
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get version {version} of prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Agent Management API Routes
# =============================================================================

# Global MAS instance reference
_global_mas_instance = None

def set_global_mas_instance(mas_instance):
    """Set global MAS instance for API access"""
    global _global_mas_instance
    _global_mas_instance = mas_instance

@router.get("/get_agents")
async def get_agents():
    """Get agents information from MAS instance"""
    try:
        global _global_mas_instance
        if _global_mas_instance is None:
            return WebResponse(code=400, message="MAS instance not available").to_dict()

        # Extract agent information from MAS
        agents = []

        # Get agents from oxy_name_to_oxy registry
        for agent_name, oxy_instance in _global_mas_instance.oxy_name_to_oxy.items():
            if hasattr(oxy_instance, '__class__') and hasattr(oxy_instance, 'desc'):
                agent_info = {
                    "name": agent_name,
                    "desc": getattr(oxy_instance, 'desc', ''),
                    "type": "agent",
                    "class_name": oxy_instance.__class__.__name__,
                    "path": [agent_name]
                }
                agents.append(agent_info)

        return WebResponse(
            code=200,
            message="Successfully retrieved agents",
            data={"agents": agents}
        ).to_dict()

    except Exception as e:
        logger.error(f"Failed to get agents: {e}")
        return WebResponse(code=500, message=f"Failed to get agents: {str(e)}").to_dict()

# ---------------------------------------------------------------------------
# Conversation Rating API Endpoints
# ---------------------------------------------------------------------------

# Initialize evaluation manager
evaluation_manager = EvaluationManager()


@router.post("/rating")
async def create_rating(rating_request: RatingRequest, request: Request):
    """Create or update conversation rating (like/dislike).

    Each conversation (trace_id) can have multiple rating records.

    Args:
        rating_request: Rating request data containing trace_id, rating_type and optional comment
        request: FastAPI request object (used to get client IP)

    Returns:
        dict: WebResponse wrapped rating result with success status and current statistics
    """
    try:
        result = await evaluation_manager.create_rating(rating_request, request)

        if result.success:
            return WebResponse(
                data={
                    "rating_id": result.rating_id,
                    "stats": result.current_stats.dict() if result.current_stats else None
                },
                message=result.message
            ).to_dict()
        else:
            return WebResponse(
                code=400,
                message=result.message,
                data={}
            ).to_dict()

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Create rating error: {error_msg}")
        return WebResponse(code=500, message="Rating operation failed").to_dict()


@router.get("/rating/{trace_id}")
async def get_rating_stats(trace_id: str):
    """Get rating statistics for a specific conversation.

    Args:
        trace_id: Conversation trace ID

    Returns:
        dict: WebResponse wrapped rating statistics
    """
    try:
        stats = await evaluation_manager.get_rating_stats(trace_id)

        if stats:
            return WebResponse(data=stats.dict()).to_dict()
        else:
            return WebResponse(
                data={
                    "trace_id": trace_id,
                    "like_count": 0,
                    "dislike_count": 0,
                    "total_ratings": 0,
                    "satisfaction_rate": 0.0
                },
                message="No rating data available"
            ).to_dict()

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Get rating stats error: {error_msg}")
        return WebResponse(code=500, message="Failed to get rating statistics").to_dict()


@router.get("/rating/{trace_id}/current")
async def get_current_rating(trace_id: str, erp: str = None):
    """Get current rating record for a specific conversation.

    Args:
        trace_id: Conversation trace ID
        erp: ERP system identifier for filtering specific ERP ratings (optional)

    Returns:
        dict: WebResponse wrapped current rating record, returns null if no rating exists
    """
    try:
        ratings = await evaluation_manager.get_rating_history(trace_id, erp=erp)

        current_rating = ratings[0] if ratings else None

        return WebResponse(
            data={
                "trace_id": trace_id,
                "current_rating": current_rating.dict() if current_rating else None
            }
        ).to_dict()

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Get current rating error: {error_msg}")
        return WebResponse(code=500, message="Failed to get current rating").to_dict()


@router.get("/rating/{trace_id}/history")
async def get_rating_history(trace_id: str, erp: str = None):
    """Get all rating history records for a specific conversation.

    Each conversation can have multiple rating records, returned in descending order by creation time.

    Args:
        trace_id: Conversation trace ID
        erp: ERP system identifier for filtering specific ERP ratings (optional)

    Returns:
        dict: WebResponse wrapped list of rating history records
    """
    try:
        history = await evaluation_manager.get_rating_history(trace_id, erp=erp)

        # Convert rating records to dictionary format
        ratings_data = [rating.dict() for rating in history]

        return WebResponse(
            data={
                "trace_id": trace_id,
                "ratings": ratings_data,
                "count": len(ratings_data),
                "erp_filter": erp
            }
        ).to_dict()

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Get rating history error: {error_msg}")
        return WebResponse(code=500, message="Failed to get rating history").to_dict()


@router.get("/debug/rating_stats/{trace_id}")
async def debug_rating_stats(trace_id: str):
    """Debug endpoint: Check rating statistics storage for specific trace_id."""
    try:
        stats = await evaluation_manager.get_rating_stats(trace_id)
        return WebResponse(data={
            "trace_id": trace_id,
            "stats": stats.dict() if stats else None,
            "found": stats is not None
        }).to_dict()
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Debug rating stats error: {error_msg}")
        return WebResponse(code=500, message=f"Debug query failed: {str(e)}").to_dict()


@router.get("/debug/trace/{trace_id}")
async def debug_trace_info(trace_id: str):
    """Debug endpoint: Query complete information for specified trace_id."""
    try:
        es_client = await get_es_client()

        # Query trace information
        trace_response = await es_client.search(
            Config.get_app_name() + "_trace",
            {"query": {"term": {"trace_id": trace_id}}, "size": 1}
        )

        trace_info = None
        if trace_response["hits"]["hits"]:
            trace_info = trace_response["hits"]["hits"][0]["_source"]

        return WebResponse(data={
            "trace_id": trace_id,
            "trace_info": trace_info,
            "found": trace_info is not None
        }).to_dict()
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Debug trace info error: {error_msg}")
        return WebResponse(code=500, message=f"Query failed: {str(e)}").to_dict()


@router.delete("/rating/clear_all")
async def clear_all_rating_data():
    """Clear all rating data (dangerous operation, for testing and maintenance only)."""
    try:
        result = await evaluation_manager.clear_all_rating_data()
        if result["success"]:
            return WebResponse(
                data=result,
                message=f"Successfully cleared data: {result['deleted_ratings']} rating records, {result['deleted_stats']} stats records"
            ).to_dict()
        else:
            return WebResponse(
                code=500,
                data=result,
                message=f"Partial clearing failed, errors: {', '.join(result['errors'])}"
            ).to_dict()
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Clear all rating data error: {error_msg}")
        return WebResponse(code=500, message=f"Failed to clear rating data: {str(e)}").to_dict()


@router.post("/rating/setup_indices")
async def setup_rating_indices():
    """Setup rating-related indexes (ensure field mappings are correct)."""
    try:
        result = await evaluation_manager.ensure_rating_indices_with_correct_mapping()
        if result["success"]:
            created_indices = []
            if result["rating_index_created"]:
                created_indices.append("rating index")
            if result["rating_stats_index_created"]:
                created_indices.append("rating stats index")

            if created_indices:
                message = f"Successfully created indexes: {', '.join(created_indices)}"
            else:
                message = "All indexes already exist, no creation needed"

            return WebResponse(data=result, message=message).to_dict()
        else:
            return WebResponse(
                code=500,
                data=result,
                message=f"Failed to setup indexes, errors: {', '.join(result['errors'])}"
            ).to_dict()
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Setup rating indices error: {error_msg}")
        return WebResponse(code=500, message=f"Failed to setup indexes: {str(e)}").to_dict()


@router.get("/history_with_ratings")
async def get_history_with_ratings(
    page: int = 1,
    page_size: int = 20,
    rating_filter: str = "all"  # "all", "liked", "disliked", "unrated"
):
    """Get conversation history list with rating information, aggregated and displayed by group_id.

    Optimized version: Only fetches rating data for the current page instead of all records.

    Args:
        page: Page number (starts from 1)
        page_size: Number of items per page
        rating_filter: Rating filter condition - "all"(all), "liked"(liked), "disliked"(disliked), "unrated"(unrated)

    Returns:
        dict: WebResponse wrapped list of conversation groups, aggregated by group_id with rating statistics
    """
    try:
        es_client = await get_es_client()

        # Phase 1: Quick aggregation to get group metadata only
        # Query all traces but only get minimal fields for grouping
        all_traces_response = await es_client.search(
            Config.get_app_name() + "_trace",
            {
                "query": {"match_all": {}},
                "_source": ["trace_id", "group_id", "create_time"],  # Only fetch essential fields
                "size": 10000,
                "sort": [{"create_time": {"order": "desc"}}],
            },
        )

        # Build lightweight group metadata
        groups_metadata = {}
        trace_to_group_map = {}

        for hit in all_traces_response["hits"]["hits"]:
            source = hit["_source"]
            trace_id = source.get("trace_id", "")
            group_id = source.get("group_id", trace_id)
            create_time = source.get("create_time", "")

            trace_to_group_map[trace_id] = group_id

            if group_id not in groups_metadata:
                groups_metadata[group_id] = {
                    "group_id": group_id,
                    "trace_ids": [],
                    "latest_create_time": create_time,
                }

            groups_metadata[group_id]["trace_ids"].append(trace_id)
            if create_time > groups_metadata[group_id]["latest_create_time"]:
                groups_metadata[group_id]["latest_create_time"] = create_time

        # Get all trace_ids for rating lookup
        all_trace_ids = list(trace_to_group_map.keys())

        # Batch retrieve rating statistics for ALL traces (still needed for filtering)
        ratings_map = await evaluation_manager.get_ratings_for_traces(all_trace_ids)

        # Calculate aggregated rating stats per group
        for group_id, metadata in groups_metadata.items():
            total_likes = 0
            total_dislikes = 0
            has_rating = False

            for trace_id in metadata["trace_ids"]:
                rating_stats = ratings_map.get(trace_id)
                if rating_stats:
                    total_likes += rating_stats.like_count
                    total_dislikes += rating_stats.dislike_count
                    if rating_stats.total_ratings > 0:
                        has_rating = True

            metadata["total_likes"] = total_likes
            metadata["total_dislikes"] = total_dislikes
            metadata["has_rating"] = has_rating

        # Filter groups based on rating criteria
        filtered_groups_metadata = []
        for group_id, metadata in groups_metadata.items():
            if rating_filter == "all":
                filtered_groups_metadata.append(metadata)
            elif rating_filter == "liked" and metadata["total_likes"] > 0:
                filtered_groups_metadata.append(metadata)
            elif rating_filter == "disliked" and metadata["total_dislikes"] > 0:
                filtered_groups_metadata.append(metadata)
            elif rating_filter == "unrated" and not metadata["has_rating"]:
                filtered_groups_metadata.append(metadata)

        # Sort by latest time
        filtered_groups_metadata.sort(key=lambda x: x["latest_create_time"], reverse=True)

        # Pagination on metadata level
        total_groups = len(filtered_groups_metadata)
        from_index = (page - 1) * page_size
        to_index = from_index + page_size
        page_groups_metadata = filtered_groups_metadata[from_index:to_index]

        # Phase 2: Only fetch full conversation details for current page
        page_trace_ids = []
        for metadata in page_groups_metadata:
            page_trace_ids.extend(metadata["trace_ids"])

        # Fetch full trace details only for current page
        page_traces_response = await es_client.search(
            Config.get_app_name() + "_trace",
            {
                "query": {"terms": {"trace_id": page_trace_ids}},
                "size": len(page_trace_ids),
            },
        )

        # Build trace details map
        trace_details_map = {}
        for hit in page_traces_response["hits"]["hits"]:
            source = hit["_source"]
            trace_id = source.get("trace_id", "")
            trace_details_map[trace_id] = source

        # Fetch rating history only for current page
        rating_histories_map = await evaluation_manager.get_rating_histories_for_traces(page_trace_ids)

        # Build final response for current page
        conversation_groups = []
        for metadata in page_groups_metadata:
            group_id = metadata["group_id"]
            conversations = []

            for trace_id in metadata["trace_ids"]:
                trace_detail = trace_details_map.get(trace_id)
                if not trace_detail:
                    continue

                conversation_data = {
                    "trace_id": trace_id,
                    "input": trace_detail.get("input", ""),
                    "callee": trace_detail.get("callee", ""),
                    "output": trace_detail.get("output", ""),
                    "create_time": trace_detail.get("create_time", ""),
                    "from_trace_id": trace_detail.get("from_trace_id", ""),
                    "group_id": group_id,
                }

                rating_stats = ratings_map.get(trace_id)
                rating_history = rating_histories_map.get(trace_id, [])

                conversation_with_rating = ConversationWithRating(
                    **conversation_data,
                    rating_stats=rating_stats,
                    rating_history=rating_history
                )
                conversations.append(conversation_with_rating.dict())

            # Sort conversations by create_time
            conversations.sort(key=lambda x: x["create_time"])

            conversation_groups.append({
                "group_id": group_id,
                "conversations": conversations,
                "latest_create_time": metadata["latest_create_time"],
                "conversation_count": len(conversations),
                "total_likes": metadata["total_likes"],
                "total_dislikes": metadata["total_dislikes"],
                "has_rating": metadata["has_rating"],
            })

        return WebResponse(
            data={
                "conversation_groups": conversation_groups,
                "total": total_groups,
                "page": page,
                "page_size": page_size,
                "total_pages": (total_groups + page_size - 1) // page_size,
            }
        ).to_dict()

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Get history with ratings error: {error_msg}")
        return WebResponse(code=500, message="Failed to get conversation history").to_dict()


@router.get("/analytics/ratings")
async def get_rating_analytics(days: int = 7):
    """Get rating statistics and analysis data.

    Args:
        days: Number of days to analyze (default 7 days)

    Returns:
        dict: WebResponse wrapped rating analytics data
    """
    try:
        stats = await evaluation_manager.get_overall_rating_stats(days)
        return WebResponse(data=stats).to_dict()

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Get rating analytics error: {error_msg}")
        return WebResponse(code=500, message="Failed to get rating analytics").to_dict()


@router.post("/rating/{trace_id}/rebuild_stats")
async def rebuild_rating_stats(trace_id: str):
    """Rebuild rating statistics for specific conversation (debug and repair function).

    Args:
        trace_id: Conversation trace ID

    Returns:
        dict: WebResponse wrapped rebuild result
    """
    try:
        # Use evaluation_manager to recalculate statistics
        es_client = await evaluation_manager._get_es_client()

        # Manually call statistics update
        stats = await evaluation_manager._update_rating_stats(es_client, trace_id)

        return WebResponse(
            data={
                "trace_id": trace_id,
                "rebuilt_stats": stats.dict(),
                "message": "Statistics recalculated"
            }
        ).to_dict()

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Rebuild rating stats error: {error_msg}")
        return WebResponse(code=500, message="Failed to rebuild statistics").to_dict()


@router.delete("/rating/{rating_id}")
async def delete_rating(rating_id: str):
    """Delete specified rating record (admin function).

    Args:
        rating_id: Rating record ID

    Returns:
        dict: WebResponse wrapped deletion result
    """
    try:
        success = await evaluation_manager.delete_rating(rating_id)

        if success:
            return WebResponse(
                data={"deleted": True, "rating_id": rating_id},
                message="Rating deleted successfully"
            ).to_dict()
        else:
            return WebResponse(
                code=404,
                message="Rating record not found"
            ).to_dict()

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Delete rating error: {error_msg}")
        return WebResponse(code=500, message="Failed to delete rating").to_dict()