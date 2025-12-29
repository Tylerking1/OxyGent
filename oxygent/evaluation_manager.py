"""Conversation evaluation data manager.

Provides storage, query, and statistical functions for conversation evaluation data.
"""

import logging
import json
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from .config import Config
from .db_factory import DBFactory
from .databases.db_es import JesEs,LocalEs
from .schemas.evaluation import (
    ConversationRating,
    RatingRequest,
    RatingStats,
    RatingType,
    RatingResponse
)

logger = logging.getLogger(__name__)


class EvaluationManager:
    """Conversation evaluation manager.

    Handles evaluation-related data operations including:
    - Storage and retrieval of rating data
    - Calculation and update of rating statistics
    - Aggregated analysis of rating data
    """

    def __init__(self):
        """Initialize evaluation manager."""
        self.db_factory = DBFactory()
        self.app_name = Config.get_app_name()
        self.rating_index = f"{self.app_name}_rating"
        self.rating_stats_index = f"{self.app_name}_rating_stats"

    def _create_empty_stats(self, trace_id: str) -> RatingStats:
        """Create empty rating statistics for a trace.

        Args:
            trace_id: Conversation trace ID

        Returns:
            RatingStats: Empty statistics object
        """
        return RatingStats(
            trace_id=trace_id,
            like_count=0,
            dislike_count=0,
            total_ratings=0,
            satisfaction_rate=0.0,
            last_updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        )

    def _get_hits_total(self, response: Optional[Dict[str, Any]]) -> int:
        """Get total number of hits from ES query response, compatible with different ES versions.

        Args:
            response: Elasticsearch query response

        Returns:
            int: Total number of matching documents
        """
        # Handle None response (index doesn't exist or query failed)
        if response is None:
            return 0

        hits = response.get("hits", {})

        # Try to get total field
        total = hits.get("total")
        if total is not None:
            if isinstance(total, dict):
                # New ES format: {"total": {"value": 1, "relation": "eq"}}
                return total.get("value", 0)
            else:
                # Old ES format: {"total": 1}
                return total

        # If no total field, use length of hits array
        hits_list = hits.get("hits", [])
        return len(hits_list)

    async def _get_es_client(self):
        """Get Elasticsearch client - supports both JesEs and LocalEs.

        Returns:
            Elasticsearch client instance (JesEs if configured, otherwise LocalEs)
        """
        jes_config = Config.get_es_config()

        # Try to use JesEs if configured
        if jes_config:
            hosts = jes_config.get("hosts")
            user = jes_config.get("user")
            password = jes_config.get("password")

            if hosts and user and password:
                return self.db_factory.get_instance(JesEs, hosts, user, password)

        # Fallback to LocalEs if JesEs is not properly configured
        logger.info("JesEs config not found or incomplete, using LocalEs for evaluation_manager")
        return self.db_factory.get_instance(LocalEs)

    def _get_client_ip(self, request) -> Optional[str]:
        """Get client IP address from request.

        Args:
            request: FastAPI request object

        Returns:
            Optional[str]: Client IP address or None if unable to determine
        """
        try:
            # Try to get IP from FastAPI request
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                return forwarded_for.split(',')[0].strip()

            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip

            return request.client.host if request.client else None
        except Exception as e:
            logger.warning(f"Failed to get client IP: {e}")
            return None

    async def _refresh_index(self, es_client, index_name: str) -> None:
        """Refresh ES index to ensure data is immediately searchable.

        Args:
            es_client: Elasticsearch client instance
            index_name: Name of the index to refresh
        """
        try:
            if hasattr(es_client, 'client') and hasattr(es_client.client.indices, 'refresh'):
                await es_client.client.indices.refresh(index=index_name)
            elif hasattr(es_client, 'refresh_index'):
                await es_client.refresh_index(index_name)
        except Exception as e:
            logger.warning(f"Failed to refresh index {index_name}: {e}")

    async def create_rating(self, rating_request: RatingRequest, request=None, user_id: Optional[str] = None) -> RatingResponse:
        """Create a new rating record (multiple rating records allowed per conversation).

        Args:
            rating_request: Rating request data
            request: FastAPI request object (used to get IP)
            user_id: User ID (optional)

        Returns:
            RatingResponse: Rating operation result
        """
        try:
            es_client = await self._get_es_client()

            # Ensure indexes exist (auto-create on first use)
            try:
                await self._ensure_rating_indexes(es_client)
            except Exception as e:
                logger.warning(f"Error ensuring indexes exist: {e}")

            # Check if conversation exists (warning only, doesn't block rating)
            trace_exists = await self._check_trace_exists(es_client, rating_request.trace_id)
            if not trace_exists:
                logger.warning(f"Trace does not exist: {rating_request.trace_id}, but allowing rating to continue")

            # Create new rating record
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            rating_id = str(uuid.uuid4())

            rating = ConversationRating(
                rating_id=rating_id,
                trace_id=rating_request.trace_id,
                rating_type=rating_request.rating_type,
                user_id=user_id,
                user_ip=self._get_client_ip(request) if request else None,
                comment=rating_request.comment,
                erp=rating_request.erp,
                create_time=current_time
            )

            # Store new rating record using rating_id as document ID to ensure uniqueness
            await es_client.index(
                self.rating_index,
                rating_id,
                rating.dict()
            )

            # Refresh index to ensure data is immediately queryable
            await self._refresh_index(es_client, self.rating_index)

            # Update statistics, passing known rating data to avoid re-querying
            stats = await self._update_rating_stats(
                es_client,
                rating_request.trace_id,
                known_rating_type=rating_request.rating_type
            )

            return RatingResponse(
                success=True,
                rating_id=rating_id,
                current_stats=stats,
                message="Rating successful"
            )

        except Exception as e:
            logger.error(f"Failed to create/update rating: {str(e)}")
            return RatingResponse(
                success=False,
                message=f"Rating failed: {str(e)}"
            )

    async def _ensure_rating_indexes(self, es_client) -> None:
        """Ensure rating-related indexes exist, create if not present.

        Args:
            es_client: ES client instance
        """
        if not hasattr(es_client, 'create_index'):
            return  # Client doesn't support index creation, skip

        # Rating record index mapping
        rating_mapping = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0
            },
            "mappings": {
                "properties": {
                    "rating_id": {"type": "keyword"},
                    "trace_id": {"type": "keyword"},
                    "rating_type": {"type": "keyword"},
                    "user_id": {"type": "keyword"},
                    "user_ip": {"type": "ip"},
                    "comment": {"type": "text"},
                    "erp": {"type": "keyword"},
                    "create_time": {"type": "keyword"},
                    "update_time": {"type": "keyword"}
                }
            }
        }

        # Rating statistics index mapping
        rating_stats_mapping = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0
            },
            "mappings": {
                "properties": {
                    "trace_id": {"type": "keyword"},
                    "like_count": {"type": "integer"},
                    "dislike_count": {"type": "integer"},
                    "total_ratings": {"type": "integer"},
                    "satisfaction_rate": {"type": "float"},
                    "last_updated": {"type": "keyword"}
                }
            }
        }

        try:
            await es_client.create_index(self.rating_index, rating_mapping)
        except Exception as e:
            logger.debug(f"Rating index already exists or creation failed: {e}")

        try:
            await es_client.create_index(self.rating_stats_index, rating_stats_mapping)
        except Exception as e:
            logger.debug(f"Stats index already exists or creation failed: {e}")

    async def _check_trace_exists(self, es_client, trace_id: str) -> bool:
        """Check if conversation trace exists.

        Args:
            es_client: ES client instance
            trace_id: Conversation trace ID

        Returns:
            bool: True if trace exists, False otherwise
        """
        try:
            trace_index = f"{self.app_name}_trace"

            # Query using trace_id.keyword field
            response = await es_client.search(
                trace_index,
                {
                    "query": {
                        "term": {"trace_id.keyword": trace_id}
                    },
                    "size": 1
                }
            )
            exists = self._get_hits_total(response) > 0

            # Log warning if not found, but don't block rating (trace data may be delayed)
            if not exists:
                logger.warning(f"Trace record not found: {trace_id}, but allowing rating to continue (possible data delay)")

            return exists
        except Exception as e:
            logger.warning(f"Failed to check trace existence: {e}", exc_info=True)
            # If check fails, return True to allow rating to continue
            return True

    async def _update_rating_stats(self, es_client, trace_id: str, known_rating_type: Optional[str] = None) -> RatingStats:
        """Update rating statistics by aggregating all rating records.

        Args:
            es_client: Elasticsearch client instance
            trace_id: Conversation trace ID
            known_rating_type: Known rating type for incremental update (optional)

        Returns:
            RatingStats: Updated rating statistics
        """
        try:
            # Initialize statistics
            like_count = 0
            dislike_count = 0
            total_ratings = 0

            # Query all rating records for this conversation
            response = await es_client.search(
                self.rating_index,
                {
                    "query": {"term": {"trace_id": trace_id}},
                    "size": 1000
                }
            )

            # Return default stats if no data found
            if response is None:
                logger.warning(f"No rating data found for trace_id {trace_id} (index may not exist)")
                return self._create_empty_stats(trace_id)

            total_ratings = self._get_hits_total(response)

            # Count ratings by type
            for hit in response["hits"]["hits"]:
                rating_data = hit["_source"]
                rating_type = rating_data["rating_type"]

                if rating_type == RatingType.LIKE:
                    like_count += 1
                elif rating_type == RatingType.DISLIKE:
                    dislike_count += 1

            # Calculate satisfaction rate percentage
            satisfaction_rate = (like_count / total_ratings * 100.0) if total_ratings > 0 else 0.0

            # Create statistics object
            stats = RatingStats(
                trace_id=trace_id,
                like_count=like_count,
                dislike_count=dislike_count,
                total_ratings=total_ratings,
                satisfaction_rate=satisfaction_rate,
                last_updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            )

            # Store or update statistics
            await es_client.index(
                self.rating_stats_index,
                trace_id,
                stats.dict()
            )

            # Force refresh index to ensure data is immediately searchable
            await self._refresh_index(es_client, self.rating_stats_index)

            return stats

        except Exception as e:
            logger.error(f"Failed to update rating stats for trace_id={trace_id}: {e}", exc_info=True)
            # Return empty stats to avoid crash
            return self._create_empty_stats(trace_id)

    async def get_rating_stats(self, trace_id: str) -> Optional[RatingStats]:
        """Get rating statistics for a conversation.

        Args:
            trace_id: Conversation trace ID

        Returns:
            Optional[RatingStats]: Rating statistics, or None if not found
        """
        try:
            es_client = await self._get_es_client()

            response = await es_client.search(
                self.rating_stats_index,
                {
                    "query": {"term": {"trace_id": trace_id}},
                    "size": 1
                }
            )

            if response is None:
                logger.warning(f"Rating stats index not found for trace_id {trace_id}")
                return None

            if self._get_hits_total(response) > 0:
                data = response["hits"]["hits"][0]["_source"]
                return RatingStats(**data)

            return None

        except Exception as e:
            logger.error(f"Failed to get rating stats for {trace_id}: {e}")
            return None

    async def get_ratings_for_traces(self, trace_ids: List[str]) -> Dict[str, RatingStats]:
        """Batch retrieve rating statistics for multiple conversations.

        Args:
            trace_ids: List of conversation trace IDs

        Returns:
            Dict[str, RatingStats]: Mapping from trace_id to rating statistics
        """
        try:
            es_client = await self._get_es_client()

            if not trace_ids:
                return {}

            response = await es_client.search(
                self.rating_stats_index,
                {
                    "query": {
                        "terms": {"trace_id": trace_ids}
                    },
                    "size": 10000
                }
            )

            if response is None:
                logger.warning(f"Rating stats index not found when fetching batch stats")
                return {}

            result = {}
            for hit in response["hits"]["hits"]:
                data = hit["_source"]
                trace_id = data["trace_id"]
                result[trace_id] = RatingStats(**data)

            return result

        except Exception as e:
            logger.error(f"Failed to get ratings for traces: {e}", exc_info=True)
            return {}

    async def get_rating_history(self, trace_id: str, erp: Optional[str] = None) -> List[ConversationRating]:
        """Get all rating history records for a conversation.

        Args:
            trace_id: Conversation trace ID
            erp: ERP system identifier for filtering specific ERP ratings (optional)

        Returns:
            List[ConversationRating]: List of rating records sorted by creation time (descending)
        """
        try:
            es_client = await self._get_es_client()

            # Build query conditions
            query = {
                "bool": {
                    "must": [{"term": {"trace_id": trace_id}}]
                }
            }
            
            # Add ERP filter condition if specified
            if erp:
                query["bool"]["must"].append({"term": {"erp": erp}})

            response = await es_client.search(
                self.rating_index,
                {
                    "query": query,
                    "size": 1000
                }
            )

            # Check if response is None (index doesn't exist or search failed)
            if response is None:
                logger.warning(f"No rating data found for trace_id {trace_id} (index may not exist)")
                return []

            ratings = []
            for hit in response["hits"]["hits"]:
                data = hit["_source"]
                ratings.append(ConversationRating(**data))

            # Sort by creation time in descending order
            ratings.sort(key=lambda x: x.create_time, reverse=True)

            return ratings

        except Exception as e:
            logger.error(f"Failed to get rating history for {trace_id}: {e}", exc_info=True)
            return []

    async def get_rating_histories_for_traces(self, trace_ids: List[str]) -> Dict[str, List[ConversationRating]]:
        """Batch retrieve rating history records for multiple conversations.

        Args:
            trace_ids: List of conversation trace IDs

        Returns:
            Dict[str, List[ConversationRating]]: Mapping from trace_id to list of rating history records
        """
        try:
            es_client = await self._get_es_client()

            if not trace_ids:
                return {}

            response = await es_client.search(
                self.rating_index,
                {
                    "query": {
                        "terms": {"trace_id": trace_ids}
                    },
                    "size": 10000,  # ES max_result_window default limit
                    "sort": [{"create_time": {"order": "desc"}}]
                }
            )

            if response is None:
                logger.warning(f"No rating data found when fetching batch histories")
                return {}

            # Group by trace_id
            result = {}
            for hit in response["hits"]["hits"]:
                data = hit["_source"]
                trace_id = data["trace_id"]
                rating = ConversationRating(**data)
                
                if trace_id not in result:
                    result[trace_id] = []
                result[trace_id].append(rating)

            # Sort ratings for each trace by creation time in descending order
            for trace_id in result:
                result[trace_id].sort(key=lambda x: x.create_time, reverse=True)

            return result

        except Exception as e:
            logger.error(f"Failed to get rating histories for traces: {e}", exc_info=True)
            return {}

    async def delete_rating(self, rating_id: str) -> bool:
        """Delete a rating record (admin function).

        Args:
            rating_id: Rating record ID or trace_id

        Returns:
            bool: Whether the deletion was successful
        """
        try:
            es_client = await self._get_es_client()

            # First try to find record by rating_id
            response = await es_client.search(
                self.rating_index,
                {
                    "query": {"term": {"rating_id": rating_id}},
                    "size": 1
                }
            )

            if response is None or self._get_hits_total(response) == 0:
                # If not found by rating_id, try searching as trace_id
                response = await es_client.search(
                    self.rating_index,
                    {
                        "query": {"term": {"trace_id.keyword": rating_id}},
                        "size": 1
                    }
                )

            if response is None or self._get_hits_total(response) == 0:
                return False

            trace_id = response["hits"]["hits"][0]["_source"]["trace_id"]
            doc_id = response["hits"]["hits"][0]["_id"]

            # Delete rating record
            await es_client.delete(self.rating_index, doc_id)

            # Recalculate statistics (will actually clear statistics)
            await self._update_rating_stats(es_client, trace_id)

            logger.info(f"Deleted rating for trace {trace_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete rating {rating_id}: {e}")
            return False

    async def get_overall_rating_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get overall rating statistics.

        Args:
            days: Number of days to include in statistics

        Returns:
            Dict[str, Any]: Overall statistics information
        """
        try:
            from datetime import datetime, timedelta

            es_client = await self._get_es_client()

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            start_date_str = start_date.strftime("%Y-%m-%d 00:00:00.000000")
            end_date_str = end_date.strftime("%Y-%m-%d 23:59:59.999999")

            # Query ratings within time range
            response = await es_client.search(
                self.rating_index,
                {
                    "query": {
                        "range": {
                            "create_time": {
                                "gte": start_date_str,
                                "lte": end_date_str
                            }
                        }
                    },
                    "size": 10000
                }
            )

            if response is None:
                logger.warning(f"Rating index not found when generating trend report")
                return {
                    "total_ratings": 0,
                    "like_count": 0,
                    "dislike_count": 0,
                    "like_rate": 0.0,
                    "daily_stats": {}
                }

            total_ratings = 0
            like_count = 0
            dislike_count = 0
            daily_stats = {}

            for hit in response["hits"]["hits"]:
                data = hit["_source"]
                total_ratings += 1

                if data["rating_type"] == RatingType.LIKE:
                    like_count += 1
                else:
                    dislike_count += 1

                # Aggregate by date
                create_time = data["create_time"]
                date_str = create_time.split()[0]
                if date_str not in daily_stats:
                    daily_stats[date_str] = {"like": 0, "dislike": 0}
                daily_stats[date_str][data["rating_type"]] += 1

            overall_satisfaction = (like_count / total_ratings * 100) if total_ratings > 0 else 0.0

            return {
                "total_ratings": total_ratings,
                "like_count": like_count,
                "dislike_count": dislike_count,
                "satisfaction_rate": round(overall_satisfaction, 2),
                "daily_stats": daily_stats,
                "time_range": {
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "days": days
                }
            }

        except Exception as e:
            logger.error(f"Failed to get overall rating stats: {e}")
            return {
                "total_ratings": 0,
                "like_count": 0,
                "dislike_count": 0,
                "satisfaction_rate": 0.0,
                "daily_stats": {},
                "error": str(e)
            }

    async def clear_all_rating_data(self) -> Dict[str, Any]:
        """Clear all rating data (including rating records and statistics).

        Returns:
            Dict[str, Any]: Cleanup result
        """
        try:
            es_client = await self._get_es_client()
            result = {
                "success": True,
                "deleted_ratings": 0,
                "deleted_stats": 0,
                "errors": []
            }

            # Delete all rating records
            try:
                rating_response = await es_client.search(
                    self.rating_index,
                    {
                        "query": {"match_all": {}},
                        "size": 1000
                    }
                )
                rating_count = self._get_hits_total(rating_response)

                if rating_count > 0:
                    # Delete rating index
                    if hasattr(es_client, 'client') and hasattr(es_client.client, 'indices'):
                        await es_client.client.indices.delete(index=self.rating_index, ignore=[400, 404])
                        result["deleted_ratings"] = rating_count
                        logger.info(f"Deleted rating index {self.rating_index}, total {rating_count} records")
                    else:
                        result["errors"].append("ES client does not support index deletion")

            except Exception as e:
                error_msg = f"Failed to delete rating records: {str(e)}"
                result["errors"].append(error_msg)
                logger.error(error_msg)

            # Delete all rating statistics
            try:
                stats_response = await es_client.search(
                    self.rating_stats_index,
                    {
                        "query": {"match_all": {}},
                        "size": 1000
                    }
                )
                stats_count = self._get_hits_total(stats_response)

                if stats_count > 0:
                    # Delete statistics index
                    if hasattr(es_client, 'client') and hasattr(es_client.client, 'indices'):
                        await es_client.client.indices.delete(index=self.rating_stats_index, ignore=[400, 404])
                        result["deleted_stats"] = stats_count
                        logger.info(f"Deleted statistics index {self.rating_stats_index}, total {stats_count} records")
                    else:
                        result["errors"].append("ES client does not support index deletion")

            except Exception as e:
                error_msg = f"Failed to delete rating statistics: {str(e)}"
                result["errors"].append(error_msg)
                logger.error(error_msg)

            if result["errors"]:
                result["success"] = False

            return result

        except Exception as e:
            logger.error(f"Failed to clear rating data: {e}", exc_info=True)
            return {
                "success": False,
                "deleted_ratings": 0,
                "deleted_stats": 0,
                "errors": [f"Clear failed: {str(e)}"]
            }

    async def ensure_rating_indices_with_correct_mapping(self) -> Dict[str, Any]:
        """Ensure rating-related indices exist with correct field mappings.

        Returns:
            Dict[str, Any]: Operation result
        """
        try:
            es_client = await self._get_es_client()
            result = {
                "success": True,
                "rating_index_created": False,
                "rating_stats_index_created": False,
                "errors": []
            }

            # Rating record index mapping
            rating_mapping = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0
                },
                "mappings": {
                    "properties": {
                        "rating_id": {"type": "keyword"},
                        "trace_id": {"type": "keyword"},
                        "rating_type": {"type": "keyword"},
                        "user_id": {"type": "keyword"},
                        "user_ip": {"type": "ip"},
                        "comment": {"type": "text"},
                        "erp": {"type": "keyword"},
                        "create_time": {"type": "keyword"},
                        "update_time": {"type": "keyword"}
                    }
                }
            }

            # Rating statistics index mapping
            rating_stats_mapping = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0
                },
                "mappings": {
                    "properties": {
                        "trace_id": {"type": "keyword"},
                        "like_count": {"type": "integer"},
                        "dislike_count": {"type": "integer"},
                        "total_ratings": {"type": "integer"},
                        "satisfaction_rate": {"type": "float"},
                        "last_updated": {"type": "keyword"}
                    }
                }
            }

            # Create rating record index
            try:
                if hasattr(es_client, 'create_index'):
                    rating_result = await es_client.create_index(self.rating_index, rating_mapping)
                    if not rating_result.get("already_exists", False):
                        result["rating_index_created"] = True
                        logger.info(f"Created rating record index: {self.rating_index}")
                    else:
                        logger.info(f"Rating record index already exists: {self.rating_index}")
                else:
                    result["errors"].append("ES client does not support index creation")
            except Exception as e:
                error_msg = f"Failed to create rating record index: {str(e)}"
                result["errors"].append(error_msg)
                logger.error(error_msg)

            # Create rating statistics index
            try:
                if hasattr(es_client, 'create_index'):
                    stats_result = await es_client.create_index(self.rating_stats_index, rating_stats_mapping)
                    if not stats_result.get("already_exists", False):
                        result["rating_stats_index_created"] = True
                        logger.info(f"Created rating statistics index: {self.rating_stats_index}")
                    else:
                        logger.info(f"Rating statistics index already exists: {self.rating_stats_index}")
                else:
                    result["errors"].append("ES client does not support index creation")
            except Exception as e:
                error_msg = f"Failed to create rating statistics index: {str(e)}"
                result["errors"].append(error_msg)
                logger.error(error_msg)

            if result["errors"]:
                result["success"] = False

            return result

        except Exception as e:
            logger.error(f"Failed to ensure index mapping: {e}", exc_info=True)
            return {
                "success": False,
                "rating_index_created": False,
                "rating_stats_index_created": False,
                "errors": [f"Operation failed: {str(e)}"]
            }