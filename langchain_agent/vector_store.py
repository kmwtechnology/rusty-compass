"""
OpenSearch-based vector store with hybrid search capabilities.

Provides:
- OpenSearchVectorStore: Main vector store with native hybrid search
- OpenSearchRetriever: LangChain-compatible retriever interface
"""

import logging
from typing import List, Optional, Dict, Any, Union

import urllib3
from opensearchpy import OpenSearch, RequestsHttpConnection
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from config import (
    RETRIEVER_K,
    RETRIEVER_FETCH_K,
    RETRIEVER_ALPHA,
    ENABLE_EMBEDDING_CACHE,
    EMBEDDING_CACHE_MAX_SIZE,
    OPENSEARCH_HOST,
    OPENSEARCH_PORT,
    OPENSEARCH_USER,
    OPENSEARCH_PASSWORD,
    OPENSEARCH_USE_SSL,
    OPENSEARCH_VERIFY_CERTS,
    OPENSEARCH_INDEX_NAME,
    OPENSEARCH_SEARCH_PIPELINE,
    OPENSEARCH_TIMEOUT,
)
from embedding_cache import EmbeddingCache
from exceptions import SearchValidationError, SearchFailureError, SearchTimeoutError, EmbeddingError

# Suppress InsecureRequestWarning for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# OpenSearch index mapping definition
INDEX_MAPPING = {
    "settings": {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "knn": True,
            "knn.algo_param.ef_search": 100,
        },
        "analysis": {
            "analyzer": {
                "english_analyzer": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "embedding": {
                "type": "knn_vector",
                "dimension": 768,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "lucene",
                    "parameters": {"ef_construction": 512, "m": 16},
                },
            },
            "chunk_text": {"type": "text", "analyzer": "english_analyzer"},
            "document_id": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "collection_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "title": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "doc_type": {"type": "keyword"},
            "url": {"type": "keyword"},
            "component_type": {"type": "keyword"},
            "class_name": {
                "type": "keyword",
                "fields": {"text": {"type": "text"}},
            },
            "component_spec": {"type": "object", "enabled": False},
            "collection": {"type": "keyword"},
            "catalog_type": {"type": "keyword"},
        }
    },
}

# Search pipeline definition for hybrid search
SEARCH_PIPELINE = {
    "description": "Hybrid search with min-max normalization and weighted combination",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {"weights": [0.5, 0.5]},
                },
            }
        }
    ],
}


def create_opensearch_client(
    host: str = OPENSEARCH_HOST,
    port: int = OPENSEARCH_PORT,
    user: str = OPENSEARCH_USER,
    password: str = OPENSEARCH_PASSWORD,
    use_ssl: bool = OPENSEARCH_USE_SSL,
    verify_certs: bool = OPENSEARCH_VERIFY_CERTS,
    timeout: int = OPENSEARCH_TIMEOUT,
) -> OpenSearch:
    """Create an OpenSearch client with connection resilience."""
    kwargs = {
        "hosts": [{"host": host, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": verify_certs,
        "ssl_show_warn": False,
        "connection_class": RequestsHttpConnection,
        "timeout": timeout,
        "retry_on_timeout": True,
        "max_retries": 3,
    }
    if user and password:
        kwargs["http_auth"] = (user, password)
    return OpenSearch(**kwargs)


class OpenSearchVectorStore:
    """
    OpenSearch-based vector store for semantic and hybrid document search.

    Uses OpenSearch's native hybrid query with normalization-processor
    search pipeline for score fusion. Falls back to client-side RRF
    if the hybrid query type is not available.

    Attributes:
        embeddings: GoogleGenerativeAIEmbeddings instance for generating query embeddings
        collection_id: Collection ID for document filtering
        client: OpenSearch client instance
        index_name: Name of the OpenSearch index
        search_pipeline: Name of the search pipeline for hybrid search
    """

    def __init__(
        self,
        embeddings: GoogleGenerativeAIEmbeddings,
        collection_id: str,
        client: Optional[OpenSearch] = None,
    ) -> None:
        if not collection_id:
            raise ValueError("collection_id must be a non-empty string")
        self.embeddings = embeddings
        self.collection_id = collection_id
        self.client = client or create_opensearch_client()
        self.index_name = OPENSEARCH_INDEX_NAME
        self.search_pipeline = OPENSEARCH_SEARCH_PIPELINE
        self._hybrid_supported: Optional[bool] = None
        # Instance-level cache for embeddings
        self._embedding_cache = EmbeddingCache(
            max_size=EMBEDDING_CACHE_MAX_SIZE,
            enabled=ENABLE_EMBEDDING_CACHE,
        )

    def _check_hybrid_support(self) -> bool:
        """Check if OpenSearch supports native hybrid queries (2.10+ with neural-search)."""
        if self._hybrid_supported is not None:
            return self._hybrid_supported

        try:
            info = self.client.info()
            version = info["version"]["number"]
            major, minor = int(version.split(".")[0]), int(version.split(".")[1])
            if major < 2 or (major == 2 and minor < 10):
                self._hybrid_supported = False
                logger.warning(f"OpenSearch {version} does not support hybrid queries (need 2.10+)")
                return False

            plugins = self.client.cat.plugins(format="json")
            has_neural = any("neural" in p.get("component", "").lower() for p in plugins)
            self._hybrid_supported = has_neural
            if not has_neural:
                logger.warning("OpenSearch neural-search plugin not found, using fallback RRF")
            return has_neural
        except Exception as e:
            logger.warning(f"Could not check hybrid support: {e}, using fallback RRF")
            self._hybrid_supported = False
            return False

    def _get_embedding(self, query: str) -> List[float]:
        """Get embedding for query, using cache if available."""
        cached = self._embedding_cache.get(query)
        if cached is not None:
            return cached

        try:
            embedding = self.embeddings.embed_query(query)
        except Exception as e:
            raise EmbeddingError(f"Failed to generate embedding: {e}") from e

        self._embedding_cache.set(query, embedding)
        return embedding

    def as_retriever(
        self,
        search_type: str = "similarity",
        search_kwargs: Optional[Dict[str, Any]] = None,
    ) -> "OpenSearchRetriever":
        """Return a retriever interface."""
        if search_kwargs is None:
            search_kwargs = {
                "k": RETRIEVER_K,
                "fetch_k": RETRIEVER_FETCH_K,
                "alpha": RETRIEVER_ALPHA,
            }

        return OpenSearchRetriever(
            self,
            search_type=search_type,
            k=search_kwargs.get("k", RETRIEVER_K),
            fetch_k=search_kwargs.get("fetch_k", RETRIEVER_FETCH_K),
            alpha=search_kwargs.get("alpha", RETRIEVER_ALPHA),
        )

    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        """
        Pure knn vector search.

        Args:
            query: The search query string
            k: Number of similar documents to return

        Returns:
            List of k most similar LangChain Document objects with metadata
        """
        try:
            query_embedding = self._get_embedding(query)

            body = {
                "size": k,
                "_source": {"excludes": ["embedding"]},
                "query": {
                    "bool": {
                        "must": [
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": k,
                                    }
                                }
                            }
                        ],
                        "filter": [
                            {"term": {"collection_id": self.collection_id}}
                        ],
                    }
                },
            }

            response = self.client.search(index=self.index_name, body=body)
            documents = [self._hit_to_document(hit) for hit in response["hits"]["hits"]]
            return self._filter_and_validate_documents(documents)

        except Exception as e:
            logger.error(f"Error during similarity search: {e}")
            return []

    def hybrid_search(
        self,
        query: str,
        k: int = 4,
        fetch_k: int = 20,
        alpha: float = 0.5,
    ) -> List[Document]:
        """
        Hybrid search combining vector similarity and full-text search.

        Uses OpenSearch's native hybrid query with normalization-processor
        search pipeline. Falls back to client-side RRF if not supported.

        Args:
            query: Search query string
            k: Number of final results to return
            fetch_k: Number of candidates to fetch from each method
            alpha: Weight for vector vs text (0.0=pure BM25, 1.0=pure vector)

        Returns:
            List of Document objects ranked by combined score
        """
        if k <= 0:
            raise SearchValidationError(f"k must be > 0, got {k}")
        if fetch_k < k:
            raise SearchValidationError(f"fetch_k ({fetch_k}) must be >= k ({k})")

        if alpha == 0.0:
            return self._text_search(query, k)

        if alpha == 1.0:
            return self.similarity_search(query, k)

        if not 0.0 <= alpha <= 1.0:
            raise SearchValidationError(f"alpha must be in [0.0, 1.0], got {alpha}")

        try:
            query_embedding = self._get_embedding(query)

            if self._check_hybrid_support():
                return self._hybrid_search_native(query, query_embedding, k, fetch_k, alpha)
            else:
                return self._hybrid_search_rrf(query, query_embedding, k, fetch_k, alpha)

        except EmbeddingError:
            raise
        except TimeoutError as e:
            raise SearchTimeoutError(f"Search timed out: {e}", operation="hybrid_search") from e
        except Exception as e:
            raise SearchFailureError(f"Hybrid search failed: {e}") from e

    def _hybrid_search_native(
        self,
        query: str,
        query_embedding: List[float],
        k: int,
        fetch_k: int,
        alpha: float,
    ) -> List[Document]:
        """Native OpenSearch hybrid search using search pipeline."""
        body = {
            "size": k,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "hybrid": {
                    "queries": [
                        {
                            "knn": {
                                "embedding": {
                                    "vector": query_embedding,
                                    "k": fetch_k,
                                    "filter": {
                                        "term": {"collection_id": self.collection_id}
                                    },
                                }
                            }
                        },
                        {
                            "bool": {
                                "must": [
                                    {
                                        "match": {
                                            "chunk_text": {
                                                "query": query,
                                            }
                                        }
                                    }
                                ],
                                "filter": [
                                    {"term": {"collection_id": self.collection_id}}
                                ],
                            }
                        },
                    ]
                }
            },
        }

        # Use search_pipeline parameter to apply normalization
        params = {"search_pipeline": self.search_pipeline}
        response = self.client.search(index=self.index_name, body=body, params=params)
        documents = [self._hit_to_document(hit) for hit in response["hits"]["hits"]]
        return self._filter_and_validate_documents(documents)

    def _hybrid_search_rrf(
        self,
        query: str,
        query_embedding: List[float],
        k: int,
        fetch_k: int,
        alpha: float,
    ) -> List[Document]:
        """Client-side RRF fallback for older OpenSearch versions."""
        RRF_K = 60

        # Vector search
        vector_body = {
            "size": fetch_k,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "bool": {
                    "must": [{"knn": {"embedding": {"vector": query_embedding, "k": fetch_k}}}],
                    "filter": [{"term": {"collection_id": self.collection_id}}],
                }
            },
        }
        vector_response = self.client.search(index=self.index_name, body=vector_body)

        # Text search
        text_body = {
            "size": fetch_k,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "bool": {
                    "must": [{"match": {"chunk_text": {"query": query}}}],
                    "filter": [{"term": {"collection_id": self.collection_id}}],
                }
            },
        }
        text_response = self.client.search(index=self.index_name, body=text_body)

        # Build rank maps
        vector_ranks = {}
        for rank, hit in enumerate(vector_response["hits"]["hits"], 1):
            vector_ranks[hit["_id"]] = (rank, hit)

        text_ranks = {}
        for rank, hit in enumerate(text_response["hits"]["hits"], 1):
            text_ranks[hit["_id"]] = (rank, hit)

        # Compute RRF scores
        all_ids = set(vector_ranks.keys()) | set(text_ranks.keys())
        vector_weight = alpha
        text_weight = 1.0 - alpha

        scored = []
        for doc_id in all_ids:
            v_rank = vector_ranks[doc_id][0] if doc_id in vector_ranks else 999999
            t_rank = text_ranks[doc_id][0] if doc_id in text_ranks else 999999
            rrf_score = (vector_weight / (RRF_K + v_rank)) + (text_weight / (RRF_K + t_rank))
            hit = vector_ranks.get(doc_id, text_ranks.get(doc_id))[1]
            scored.append((rrf_score, hit))

        scored.sort(key=lambda x: x[0], reverse=True)
        documents = [self._hit_to_document(hit) for _, hit in scored[:k]]
        return self._filter_and_validate_documents(documents)

    def _text_search(self, query: str, k: int = 4) -> List[Document]:
        """Pure BM25 text search for alpha=0.0."""
        try:
            body = {
                "size": k,
                "_source": {"excludes": ["embedding"]},
                "query": {
                    "bool": {
                        "must": [{"match": {"chunk_text": {"query": query}}}],
                        "filter": [{"term": {"collection_id": self.collection_id}}],
                    }
                },
            }

            response = self.client.search(index=self.index_name, body=body)
            documents = [self._hit_to_document(hit) for hit in response["hits"]["hits"]]
            return self._filter_and_validate_documents(documents)

        except Exception as e:
            logger.error(f"Error during text search: {e}")
            return []

    def list_components(self, component_type: str) -> List[Dict]:
        """
        List all components of a given type with their specs.

        Args:
            component_type: "stage", "connector", "indexer", "core", or "other_api"

        Returns:
            List of metadata dicts containing class_name, component_spec, title, etc.
        """
        from exceptions import OpenSearchError

        try:
            body = {
                "size": 1000,
                "_source": {
                    "excludes": ["embedding", "chunk_text"],
                },
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"collection_id": self.collection_id}},
                            {"term": {"component_type": component_type}},
                            {"term": {"doc_type": "api_reference"}},
                        ]
                    }
                },
                "sort": [{"class_name": {"order": "asc"}}],
                "collapse": {"field": "document_id"},
            }

            response = self.client.search(index=self.index_name, body=body)
            results = []
            for hit in response["hits"]["hits"]:
                src = hit["_source"]
                metadata = {
                    "source": src.get("source", ""),
                    "title": src.get("title", ""),
                    "doc_type": src.get("doc_type", ""),
                    "url": src.get("url", ""),
                    "collection": src.get("collection", ""),
                    "component_type": src.get("component_type", ""),
                    "class_name": src.get("class_name", ""),
                }
                if "component_spec" in src:
                    metadata["component_spec"] = src["component_spec"]
                results.append(metadata)
            return results

        except Exception as e:
            logger.error(f"Vector store: Error listing {component_type}", extra={"error": str(e)})
            raise OpenSearchError(
                f"Unable to list {component_type} components",
                operation="list_components",
                index=self.index_name,
                recoverable=True,
            )

    def get_component_spec(self, class_name: str) -> Optional[Dict]:
        """
        Look up a component spec by class name (fully-qualified or short name).

        Args:
            class_name: e.g. "CopyFields" or "com.kmwllc.lucille.stage.CopyFields"

        Returns:
            Component spec dict, or None if not found
        """
        from exceptions import OpenSearchError

        try:
            # Try exact match first (check multiple chunks since
            # component_spec is stored with enabled:false and can't be queried)
            body = {
                "size": 5,
                "_source": ["component_spec"],
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"collection_id": self.collection_id}},
                            {"term": {"class_name": class_name}},
                        ]
                    }
                },
            }
            response = self.client.search(index=self.index_name, body=body)
            for hit in response["hits"]["hits"]:
                spec = hit["_source"].get("component_spec")
                if spec:
                    return spec

            # Try wildcard match for short class name
            body["query"]["bool"]["filter"][1] = {
                "wildcard": {"class_name": f"*.{class_name}"}
            }
            response = self.client.search(index=self.index_name, body=body)
            for hit in response["hits"]["hits"]:
                spec = hit["_source"].get("component_spec")
                if spec:
                    return spec

            return None

        except Exception as e:
            logger.error(f"Vector store: Error looking up {class_name}", extra={"error": str(e)})
            raise OpenSearchError(
                f"Unable to lookup component spec for {class_name}",
                operation="get_component_spec",
                index=self.index_name,
                recoverable=True,
            )

    def get_components_by_type(self, component_type: str) -> List[Document]:
        """
        Get full Document objects for all components of a given type.

        Args:
            component_type: "stage", "connector", "indexer", etc.

        Returns:
            List of LangChain Document objects with full content and metadata
        """
        from exceptions import OpenSearchError

        try:
            body = {
                "size": 1000,
                "_source": {"excludes": ["embedding"]},
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"collection_id": self.collection_id}},
                            {"term": {"component_type": component_type}},
                        ]
                    }
                },
                "sort": [{"class_name": {"order": "asc"}}],
                "collapse": {"field": "document_id"},
            }

            response = self.client.search(index=self.index_name, body=body)
            return [self._hit_to_document(hit) for hit in response["hits"]["hits"]]

        except Exception as e:
            logger.error(f"Vector store: Error getting {component_type}", extra={"error": str(e)})
            raise OpenSearchError(
                f"Unable to get {component_type} components",
                operation="get_components_by_type",
                index=self.index_name,
                recoverable=True,
            )

    @staticmethod
    def _hit_to_document(hit: dict) -> Document:
        """Convert an OpenSearch hit to a LangChain Document."""
        src = hit["_source"]
        metadata = {
            "source": src.get("source", ""),
            "title": src.get("title", ""),
            "doc_type": src.get("doc_type", ""),
            "url": src.get("url", ""),
            "collection": src.get("collection", ""),
            "component_type": src.get("component_type", ""),
            "class_name": src.get("class_name", ""),
        }
        if "component_spec" in src:
            metadata["component_spec"] = src["component_spec"]
        if "catalog_type" in src:
            metadata["catalog_type"] = src["catalog_type"]
        return Document(page_content=src.get("chunk_text", ""), metadata=metadata)

    def _filter_and_validate_documents(self, documents: List[Document]) -> List[Document]:
        """
        Filter and validate documents for data quality issues.

        Removes documents with None page_content and logs warnings.
        This prevents downstream errors when processing document content.

        Args:
            documents: List of documents to validate

        Returns:
            Filtered list of valid documents
        """
        if not documents:
            return documents

        valid_docs = []
        invalid_count = 0

        for doc in documents:
            if doc.page_content is None:
                invalid_count += 1
                source = doc.metadata.get("source", "unknown")
                logger.warning(
                    f"Document with None page_content filtered out",
                    extra={"source": source, "metadata": doc.metadata}
                )
            else:
                valid_docs.append(doc)

        if invalid_count > 0:
            logger.warning(
                f"Filtered {invalid_count} documents with None page_content "
                f"from {len(documents)} total results"
            )

        return valid_docs


class OpenSearchRetriever:
    """Retriever interface for OpenSearch vector store."""

    def __init__(
        self,
        vector_store: OpenSearchVectorStore,
        search_type: str = "similarity",
        k: int = 4,
        fetch_k: int = 20,
        alpha: float = 0.5,
    ) -> None:
        self.vector_store = vector_store
        self.search_type = search_type
        self.k = k
        self.fetch_k = fetch_k
        self.alpha = alpha

    def invoke(
        self,
        input_dict: Union[Dict[str, Any], str],
    ) -> List[Document]:
        """
        Retrieve documents for a query.

        Args:
            input_dict: Either a dictionary with 'input' or 'query' key,
                       or a string query directly

        Returns:
            List of Document objects matching the query
        """
        if isinstance(input_dict, dict):
            query = input_dict.get("input") or input_dict.get("query", "")
        else:
            query = str(input_dict)

        if self.search_type == "hybrid":
            return self.vector_store.hybrid_search(
                query,
                k=self.k,
                fetch_k=self.fetch_k,
                alpha=self.alpha,
            )
        elif self.search_type == "similarity":
            return self.vector_store.similarity_search(query, k=self.k)
        else:
            raise ValueError(f"Unknown search_type: {self.search_type}")
