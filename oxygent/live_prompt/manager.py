"""Live Prompt Management Service for OxyGent framework.

This module provides dynamic prompt management capabilities, supporting storage and
real-time updates through Elasticsearch or LocalEs backends. It enables hot-swapping
of prompts during runtime and maintains version history for all prompt changes.
The system automatically falls back to LocalEs when Elasticsearch is unavailable.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from oxygent import Config
from ..databases.db_es import JesEs, LocalEs

logger = logging.getLogger(__name__)


def get_es_config():
    """Get Elasticsearch configuration from Config.

    Retrieves ES configuration including hosts, authentication, and connection
    parameters from the Config system with fallback to default values.

    Returns:
        tuple: A tuple containing (hosts_list, es_params_dict)
    """
    try:
        # Use Config's dedicated method to get ES configuration
        es_config = Config.get_es_config()

        if not es_config:
            logger.warning("ES config is empty, using defaults")
            return ["localhost:9200"], {}

        # Build ES host list
        hosts = es_config.get("hosts", ["localhost:9200"])
        if isinstance(hosts, str):
            hosts = [hosts]

        # Handle authentication information
        es_params = {}
        if "user" in es_config and "password" in es_config:
            if es_config["user"] and es_config["password"]:
                es_params["http_auth"] = (es_config["user"], es_config["password"])

        # Add other ES settings
        es_params["timeout"] = es_config.get("timeout", 30)
        es_params["max_retries"] = es_config.get("max_retries", 3)
        es_params["retry_on_timeout"] = es_config.get("retry_on_timeout", True)

        logger.info(f"Read ES config from Config: hosts={hosts}, auth={bool(es_params.get('http_auth'))}")
        return hosts, es_params
    except Exception as e:
        logger.warning(f"Failed to get ES config from Config, using defaults: {e}")
        return ["localhost:9200"], {}


class PromptManager:
    """Prompt management system with automatic ES/LocalEs fallback.

    This class provides comprehensive prompt management capabilities including
    storage, retrieval, versioning, and hot-reloading. It automatically switches
    between Elasticsearch and LocalEs backends based on availability.

    Attributes:
        index_name (str): The Elasticsearch index name for storing prompts.
        use_local_es (bool): Whether currently using LocalEs as backend.
        db_client: The database client instance (JesEs or LocalEs).
    """

    def __init__(self, es_host: str = None, index_name: str = "live_prompts"):
        """Initialize the prompt manager.

        Args:
            es_host (str, optional): ES host address. If not provided, automatically
                selects between ES and LocalEs based on configuration.
            index_name (str): Index name for storing prompts. Defaults to "live_prompts".
        """
        self.index_name = index_name
        self._prompt_cache = {}  # Memory cache for prompt content
        self._last_update = {}   # Last update timestamps
        self.db_client = None
        self.use_local_es = False

        # Initialize database client
        self._init_db_client(es_host)

    def _init_db_client(self, es_host: str = None):
        """Initialize database client with JesEs priority and LocalEs fallback.

        Attempts to initialize JesEs first using configuration or provided host.
        Falls back to LocalEs if JesEs initialization fails or credentials are unavailable.

        Args:
            es_host (str, optional): Specific ES host to use instead of config.
        """
        try:
            if es_host:
                # Use provided host address with credentials from config
                hosts, es_params = get_es_config()
                user = es_params.get("http_auth", ("", ""))[0] if es_params.get("http_auth") else ""
                password = es_params.get("http_auth", ("", ""))[1] if es_params.get("http_auth") else ""

                if not user or not password:
                    logger.warning("ES credentials not available, will use LocalEs")
                    raise ValueError("ES credentials not available")

                self.db_client = JesEs([es_host], user, password)
                logger.info(f"Using specified ES host: {es_host}")
            else:
                # Try to use JesEs with config
                hosts, es_params = get_es_config()
                user = es_params.get("http_auth", ("", ""))[0] if es_params.get("http_auth") else ""
                password = es_params.get("http_auth", ("", ""))[1] if es_params.get("http_auth") else ""

                if not user or not password:
                    logger.info("ES credentials not configured, using LocalEs")
                    raise ValueError("ES credentials not available in config")

                self.db_client = JesEs(hosts, user, password)
                logger.info(f"Using JesEs configuration: {hosts}")
        except Exception as e:
            logger.info(f"JesEs initialization failed, switching to LocalEs: {e}")
            # Fallback to LocalEs
            self.db_client = LocalEs()
            self.use_local_es = True
            logger.info("Using LocalEs as storage backend")

    async def init_index(self):
        """Initialize index for prompt storage.

        Creates the necessary index structure for ES or prepares LocalEs.
        For JesEs, creates index with proper mapping if it doesn't exist.
        For LocalEs, no explicit index creation is needed.
        """
        try:
            if self.use_local_es:
                # LocalEs doesn't need explicit index creation
                logger.info("LocalEs ready, no index creation needed")
                return

            # For JesEs, check and create index
            index_exists = await self.db_client.index_exists(self.index_name)
            if not index_exists:
                # Create index mapping
                mapping = {
                    "mappings": {
                        "properties": {
                            "prompt_key": {
                                "type": "keyword"  # Prompt key for exact matching
                            },
                            "prompt_content": {
                                "type": "text",
                                "analyzer": "standard"  # Prompt content
                            },
                            "description": {
                                "type": "text"  # Prompt description
                            },
                            "category": {
                                "type": "keyword"  # Category: system, expert, workflow, etc.
                            },
                            "agent_type": {
                                "type": "keyword"  # Corresponding Agent type
                            },
                            "version": {
                                "type": "integer"  # Version number
                            },
                            "is_active": {
                                "type": "boolean"  # Whether active
                            },
                            "created_at": {
                                "type": "date"
                            },
                            "updated_at": {
                                "type": "date"
                            },
                            "created_by": {
                                "type": "keyword"  # Creator
                            },
                            "tags": {
                                "type": "keyword"  # Tags
                            }
                        }
                    }
                }

                await self.db_client.create_index(self.index_name, mapping)
                logger.info(f"Created ES index: {self.index_name}")
            else:
                logger.info(f"ES index already exists: {self.index_name}")

        except Exception as e:
            logger.error(f"Failed to init ES index: {e}")
            # If ES initialization fails, switch to LocalEs
            if not self.use_local_es:
                logger.warning("ES index initialization failed, switching to LocalEs")
                self.db_client = LocalEs()
                self.use_local_es = True
                logger.info("Switched to LocalEs as storage backend")

    async def save_prompt(self, prompt_key: str, prompt_content: str,
                         description: str = "", category: str = "custom",
                         agent_type: str = "", version: int = 1,
                         is_active: bool = True, tags: List[str] = None,
                         created_by: str = "user") -> bool:
        """Save or update a prompt with version history.

        Saves a new prompt or updates an existing one, automatically handling
        version increments and history preservation. The previous version is
        archived before updating.

        Args:
            prompt_key (str): Unique identifier for the prompt.
            prompt_content (str): The actual prompt content.
            description (str): Human-readable description. Defaults to "".
            category (str): Prompt category. Defaults to "custom".
            agent_type (str): Associated agent type. Defaults to "".
            version (int): Version number. Defaults to 1.
            is_active (bool): Whether the prompt is active. Defaults to True.
            tags (List[str], optional): List of tags for categorization.
            created_by (str): Creator identifier. Defaults to "user".

        Returns:
            bool: True if save was successful, False otherwise.
        """
        try:
            # Check if prompt already exists
            existing = await self.get_prompt(prompt_key)

            doc = {
                "prompt_key": prompt_key,
                "prompt_content": prompt_content,
                "description": description,
                "category": category,
                "agent_type": agent_type,
                "version": version,
                "is_active": is_active,
                "updated_at": datetime.now().isoformat(),
                "tags": tags or []
            }

            if existing:
                # Save current version to history
                history_id = f"{prompt_key}_v{existing.get('version', 1)}"
                history_doc = existing.copy()
                history_doc["is_history"] = True
                history_doc["history_id"] = history_id
                history_doc["archived_at"] = datetime.now().isoformat()

                try:
                    await self.db_client.index(
                        index_name=f"{self.index_name}_history",
                        doc_id=history_id,
                        body=history_doc
                    )
                except Exception as e:
                    logger.warning(f"Failed to save history for {prompt_key}: {e}")

                # Update existing record
                doc["created_at"] = existing.get("created_at")
                doc["created_by"] = existing.get("created_by", created_by)
                doc["version"] = existing.get("version", 1) + 1
            else:
                # Create new record
                doc["created_at"] = datetime.now().isoformat()
                doc["created_by"] = created_by

            # Save to database
            await self.db_client.index(
                index_name=self.index_name,
                doc_id=prompt_key,
                body=doc
            )

            # Update cache
            self._prompt_cache[prompt_key] = prompt_content
            self._last_update[prompt_key] = datetime.now()

            logger.info(f"Saved prompt: {prompt_key}")
            return True

        except Exception as e:
            logger.error(f"Failed to save prompt {prompt_key}: {e}")
            return False

    async def get_prompt(self, prompt_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a prompt by its key.

        Fetches prompt data from the database and updates the local cache.
        Returns the complete prompt document including metadata.

        Args:
            prompt_key (str): The unique identifier for the prompt.

        Returns:
            Optional[Dict[str, Any]]: The prompt data dict if found, None otherwise.
        """
        try:
            # Fetch single document from database
            search_body = {
                "query": {
                    "term": {
                        "_id": prompt_key
                    }
                },
                "size": 1
            }

            response = await self.db_client.search(
                index_name=self.index_name,
                body=search_body
            )

            hits = response.get("hits", {}).get("hits", [])
            if hits:
                source = hits[0]["_source"]
                # Update cache
                self._prompt_cache[prompt_key] = source["prompt_content"]
                self._last_update[prompt_key] = datetime.now()
                return source

            return None

        except Exception as e:
            logger.error(f"Failed to get prompt {prompt_key}: {e}")
            return None

    async def get_prompt_content(self, prompt_key: str, fallback_content: str = "") -> str:
        """Get prompt content with fallback support.

        Retrieves the content of an active prompt. If the prompt doesn't exist
        or is inactive, returns the provided fallback content.

        Args:
            prompt_key (str): The unique identifier for the prompt.
            fallback_content (str): Content to return if prompt not found or inactive.

        Returns:
            str: The prompt content or fallback content.
        """
        prompt_data = await self.get_prompt(prompt_key)
        if prompt_data and prompt_data.get("is_active", True):
            return prompt_data["prompt_content"]
        return fallback_content

    async def get_prompt_history(self, prompt_key: str) -> List[Dict[str, Any]]:
        """Get prompt version history.

        Retrieves the version history for a specific prompt, sorted by version
        number in descending order. Uses fallback query if keyword search fails.

        Args:
            prompt_key (str): The unique identifier for the prompt.

        Returns:
            List[Dict[str, Any]]: List of version history, sorted by version descending.
        """
        try:
            # Search history records - fixed query logic
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"prompt_key.keyword": prompt_key}},  # Use keyword field
                            {"term": {"is_history": True}}
                        ]
                    }
                },
                "sort": [{"version": {"order": "desc"}}],
                "size": 50  # Return maximum 50 versions
            }

            response = await self.db_client.search(
                index_name=f"{self.index_name}_history",
                body=query
            )

            histories = []
            for hit in response["hits"]["hits"]:
                histories.append(hit["_source"])

            # If keyword query still fails, try without keyword
            if len(histories) == 0:
                query_fallback = {
                    "query": {
                        "bool": {
                            "must": [
                                {"match": {"prompt_key": prompt_key}},
                                {"term": {"is_history": True}}
                            ]
                        }
                    },
                    "sort": [{"version": {"order": "desc"}}],
                    "size": 50
                }

                response = await self.db_client.search(
                    index_name=f"{self.index_name}_history",
                    body=query_fallback
                )

                for hit in response["hits"]["hits"]:
                    histories.append(hit["_source"])

            return histories

        except Exception as e:
            logger.error(f"Failed to get prompt history for {prompt_key}: {e}")
            return []

    async def revert_to_version(self, prompt_key: str, target_version: int) -> bool:
        """Revert prompt to a specific version.

        Retrieves the specified version from history and creates a new version
        with that content, effectively reverting the prompt to the target version.

        Args:
            prompt_key (str): The unique identifier for the prompt.
            target_version (int): The target version number to revert to.

        Returns:
            bool: True if reversion was successful, False otherwise.
        """
        try:
            # Get target version from history
            history_id = f"{prompt_key}_v{target_version}"

            try:
                # Use search instead of get method
                search_body = {
                    "query": {
                        "term": {
                            "_id": history_id
                        }
                    },
                    "size": 1
                }

                response = await self.db_client.search(
                    index_name=f"{self.index_name}_history",
                    body=search_body
                )

                hits = response.get("hits", {}).get("hits", [])
                if not hits:
                    logger.error(f"Version {target_version} not found for {prompt_key}")
                    return False

                history_data = hits[0]["_source"]

            except Exception as e:
                logger.error(f"Version {target_version} not found for {prompt_key}: {e}")
                return False

            # Create new version using historical data
            success = await self.save_prompt(
                prompt_key=prompt_key,
                prompt_content=history_data["prompt_content"],
                description=history_data.get("description", ""),
                category=history_data.get("category", "custom"),
                agent_type=history_data.get("agent_type", ""),
                is_active=history_data.get("is_active", True),
                tags=history_data.get("tags", []),
                created_by=f"reverted_from_v{target_version}"
            )

            if success:
                logger.info(f"Successfully reverted {prompt_key} to version {target_version}")

            return success

        except Exception as e:
            logger.error(f"Failed to revert {prompt_key} to version {target_version}: {e}")
            return False

    async def list_prompts(self, category: str = None, agent_type: str = None,
                          is_active: bool = None, tags: List[str] = None) -> List[Dict[str, Any]]:
        """List prompts with optional filtering.

        Retrieves all prompts matching the specified criteria. Supports filtering
        by category, agent type, active status, and tags.

        Args:
            category (str, optional): Filter by category.
            agent_type (str, optional): Filter by agent type.
            is_active (bool, optional): Filter by active status.
            tags (List[str], optional): Filter by tags.

        Returns:
            List[Dict[str, Any]]: List of matching prompts.
        """
        try:
            query = {"match_all": {}}
            filters = []

            if category:
                filters.append({"term": {"category": category}})
            if agent_type:
                filters.append({"term": {"agent_type": agent_type}})
            if is_active is not None:
                filters.append({"term": {"is_active": is_active}})
            if tags:
                for tag in tags:
                    filters.append({"term": {"tags": tag}})

            if filters:
                query = {
                    "bool": {
                        "must": [{"match_all": {}}],
                        "filter": filters
                    }
                }

            # run search
            response = await self.db_client.search(
                index_name=self.index_name,
                body={
                    "query": query,
                    "sort": [{"updated_at": {"order": "desc"}}],
                    "size": 1000
                }
            )

            results = []
            for hit in response["hits"]["hits"]:
                result = hit["_source"]
                result["id"] = hit["_id"]
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"Failed to list prompts: {e}")
            return []

    async def delete_prompt(self, prompt_key: str) -> bool:
        """Delete a prompt.

        Removes the prompt from the database and clears it from the local cache.

        Args:
            prompt_key (str): The unique identifier for the prompt.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        try:
            await self.db_client.delete(
                index_name=self.index_name,
                doc_id=prompt_key
            )

            # Clear cache
            if prompt_key in self._prompt_cache:
                del self._prompt_cache[prompt_key]
            if prompt_key in self._last_update:
                del self._last_update[prompt_key]

            logger.info(f"Deleted prompt: {prompt_key}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete prompt {prompt_key}: {e}")
            return False

    async def search_prompts(self, keyword: str, category: str = None) -> List[Dict[str, Any]]:
        """Search prompts by keyword with optional category filter.

        Performs full-text search across prompt fields including key, description,
        content, and tags. Results are scored and sorted by relevance.

        Args:
            keyword (str): The search keyword.
            category (str, optional): Filter by category.

        Returns:
            List[Dict[str, Any]]: List of matching prompts with search scores.
        """
        try:
            # Build search query
            must_queries = [
                {
                    "multi_match": {
                        "query": keyword,
                        "fields": ["prompt_key^2", "description^1.5", "prompt_content", "tags^1.2"],
                        "type": "best_fields"
                    }
                }
            ]

            filters = []
            if category:
                filters.append({"term": {"category": category}})

            query = {
                "bool": {
                    "must": must_queries,
                    "filter": filters
                }
            }

            # Execute search
            response = await self.db_client.search(
                index_name=self.index_name,
                body={
                    "query": query,
                    "highlight": {
                        "fields": {
                            "description": {},
                            "prompt_content": {"fragment_size": 150}
                        }
                    },
                    "sort": [{"_score": {"order": "desc"}}],
                    "size": 50
                }
            )

            results = []
            for hit in response["hits"]["hits"]:
                result = hit["_source"]
                result["id"] = hit["_id"]
                result["score"] = hit["_score"]
                if "highlight" in hit:
                    result["highlight"] = hit["highlight"]
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"Failed to search prompts: {e}")
            return []

    async def close(self):
        """Close the database connection.

        Properly closes the underlying database client connection to free resources.
        Should be called when the PromptManager is no longer needed.
        """
        await self.db_client.close()


# Global prompt manager instance
prompt_manager = None

async def get_prompt_manager() -> PromptManager:
    """Get the global prompt manager instance.

    Returns the singleton PromptManager instance, creating it if necessary.
    The instance is automatically configured using Config settings.

    Returns:
        PromptManager: The global prompt manager instance.
    """
    global prompt_manager
    if prompt_manager is None:
        # Read ES config from Config, no longer using environment variables
        prompt_manager = PromptManager()  # Don't pass es_host, let it auto-read from Config
        await prompt_manager.init_index()
    return prompt_manager


async def get_dynamic_prompt(prompt_key: str, fallback_content: str = "") -> str:
    """Get dynamic prompt content with ES priority and fallback support.

    Retrieves prompt content from the prompt management system. If the prompt
    doesn't exist or is inactive, returns the provided fallback content.
    This function provides a convenient interface for dynamic prompt loading.

    Args:
        prompt_key (str): The unique identifier for the prompt.
        fallback_content (str): Fallback content (original static prompt) to use
            if the dynamic prompt is not available. Defaults to "".

    Returns:
        str: The prompt content from ES/LocalEs or fallback content.
    """
    try:
        manager = await get_prompt_manager()
        return await manager.get_prompt_content(prompt_key, fallback_content)
    except Exception as e:
        logger.error(f"Failed to get dynamic prompt {prompt_key}: {e}")
        return fallback_content