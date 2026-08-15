"""Platform configs (env-driven) and a small GraphClient interface so
load.py/workloads.py/mixed_workload.py write query logic once and it runs
against every Bolt+Cypher platform (CognoDB, Aura, Neo4j Community, Memgraph)
plus the one AQL platform (ArangoDB) through the same call shape.

Node schema loaded on every platform: (:User {id, age})
Edge schema: (:User)-[:FRIEND]->(:User)
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Iterable

from dotenv import load_dotenv

from bench.models import PlatformConfig, PlatformName, QueryDialect

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# Advertised specs are what each README table cites; keep in one place.
PLATFORM_DEFS: dict[PlatformName, dict[str, Any]] = {
    PlatformName.COGNODB: dict(
        uri_env="COGNODB_URI", user_env="COGNODB_USER", password_env="COGNODB_PASSWORD",
        dialect=QueryDialect.CYPHER, vcpu=0.5, ram_mb=256, disk_gb=1, managed=True,
    ),
    PlatformName.AURA: dict(
        uri_env="AURA_URI", user_env="AURA_USER", password_env="AURA_PASSWORD",
        dialect=QueryDialect.CYPHER, vcpu=0.5, ram_mb=256, disk_gb=1, managed=True,
    ),
    PlatformName.NEO4J_COMMUNITY: dict(
        uri_env="NEO4J_COMMUNITY_URI", user_env="NEO4J_COMMUNITY_USER",
        password_env="NEO4J_COMMUNITY_PASSWORD",
        dialect=QueryDialect.CYPHER, vcpu=0.5, ram_mb=256, disk_gb=1, managed=False,
    ),
    PlatformName.MEMGRAPH: dict(
        uri_env="MEMGRAPH_URI", user_env="MEMGRAPH_USER", password_env="MEMGRAPH_PASSWORD",
        dialect=QueryDialect.CYPHER, vcpu=0.5, ram_mb=256, disk_gb=1, managed=False,
    ),
    PlatformName.ARANGODB: dict(
        uri_env="ARANGODB_URI", user_env="ARANGODB_USER", password_env="ARANGODB_PASSWORD",
        dialect=QueryDialect.AQL, vcpu=0.5, ram_mb=256, disk_gb=1, managed=False,
    ),
}


def load_platform_configs(only: Iterable[str] | None = None) -> dict[PlatformName, PlatformConfig]:
    """Build configs for every platform with a non-empty URI, optionally filtered by name."""
    wanted = set(only) if only else None
    configs: dict[PlatformName, PlatformConfig] = {}
    for name, spec in PLATFORM_DEFS.items():
        if wanted and name.value not in wanted:
            continue
        uri = _env(spec["uri_env"])
        if not uri:
            continue
        configs[name] = PlatformConfig(
            name=name,
            uri=uri,
            user=_env(spec["user_env"]),
            password=_env(spec["password_env"]),
            dialect=spec["dialect"],
            advertised_vcpu=spec["vcpu"],
            advertised_ram_mb=spec["ram_mb"],
            advertised_disk_gb=spec["disk_gb"],
            managed=spec["managed"],
        )
    return configs


class GraphClient(ABC):
    """Common surface every workload/loader calls through."""

    def __init__(self, config: PlatformConfig):
        self.config = config

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def ensure_schema(self) -> list[str]:
        """Create the indexed property('s) index; return the list of indexed property names."""

    @abstractmethod
    def load_nodes(self, nodes: list[dict]) -> int:
        """Batch-insert nodes shaped {id, age}; return count inserted."""

    @abstractmethod
    def load_edges(self, edges: list[dict]) -> int:
        """Batch-insert edges shaped {src, dst}; return count inserted."""

    @abstractmethod
    def run_traversal(self, start_id: str, hops: int) -> Any: ...

    @abstractmethod
    def run_point_lookup(self, node_id: str) -> Any: ...

    @abstractmethod
    def run_indexed_lookup(self, min_age: int, max_age: int) -> Any: ...

    @abstractmethod
    def run_aggregation(self) -> Any: ...

    @abstractmethod
    def run_mixed_read(self, node_id: str) -> Any: ...

    @abstractmethod
    def run_mixed_write(self, src_id: str, dst_id: str) -> Any: ...

    @abstractmethod
    def footprint(self) -> dict[str, float | None]:
        """Best-effort {stored_data_mb, memory_mb}; None where not observable."""

    def __enter__(self) -> "GraphClient":
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


_CYPHER_TRAVERSAL = {
    1: "MATCH (a:User {id: $id})-[:FRIEND]->(b:User) RETURN count(b) AS c",
    2: "MATCH (a:User {id: $id})-[:FRIEND*2]->(b:User) RETURN count(b) AS c",
    3: "MATCH (a:User {id: $id})-[:FRIEND*3]->(b:User) RETURN count(b) AS c",
}


class Neo4jBoltClient(GraphClient):
    """Works for CognoDB, Aura, Neo4j Community, and Memgraph — all Bolt+Cypher."""

    def __init__(self, config: PlatformConfig):
        super().__init__(config)
        self._driver = None

    def connect(self) -> None:
        from neo4j import GraphDatabase

        auth = (self.config.user, self.config.password.get_secret_value()) if self.config.user else None
        # Bound connection + retry time so a dead free-tier connection fails
        # fast and loudly instead of hanging silently on a stale TCP read.
        # CognoDB's free tier appears to silently kill idle/long-lived pooled
        # connections around ~15s; max_connection_lifetime forces the pool to
        # proactively recycle connections before that happens, rather than
        # reactively hitting a "defunct connection" error on reuse.
        self._driver = GraphDatabase.driver(
            self.config.uri,
            auth=auth,
            connection_timeout=15,
            max_transaction_retry_time=8,
            max_connection_lifetime=5,
        )
        self._driver.verify_connectivity()

    def close(self) -> None:
        if self._driver:
            self._driver.close()

    def ensure_schema(self) -> list[str]:
        # Memgraph's Cypher dialect doesn't support Neo4j 5.x's named
        # `CREATE INDEX ... IF NOT EXISTS FOR (n:Label) ON (n.prop)` form.
        if self.config.name == PlatformName.MEMGRAPH:
            index_queries = ["CREATE INDEX ON :User(id)", "CREATE INDEX ON :User(age)"]
        else:
            index_queries = [
                "CREATE INDEX user_id_idx IF NOT EXISTS FOR (u:User) ON (u.id)",
                "CREATE INDEX user_age_idx IF NOT EXISTS FOR (u:User) ON (u.age)",
            ]
        with self._driver.session() as s:
            for query in index_queries:
                if self.config.name == PlatformName.MEMGRAPH:
                    # Memgraph rejects index DDL inside an explicit/managed
                    # transaction ("Index manipulation not allowed in
                    # multicommand transactions") — must be auto-commit.
                    s.run(query).consume()
                else:
                    s.execute_write(lambda tx, q=query: tx.run(q).consume())
        return ["id", "age"]

    def load_nodes(self, nodes: list[dict]) -> int:
        with self._driver.session() as s:
            s.execute_write(
                lambda tx: tx.run(
                    "UNWIND $rows AS row CREATE (:User {id: row.id, age: row.age})",
                    rows=nodes,
                ).consume()
            )
        return len(nodes)

    def load_edges(self, edges: list[dict]) -> int:
        with self._driver.session() as s:
            s.execute_write(
                lambda tx: tx.run(
                    "UNWIND $rows AS row "
                    "MATCH (a:User {id: row.src}), (b:User {id: row.dst}) "
                    "CREATE (a)-[:FRIEND]->(b)",
                    rows=edges,
                ).consume()
            )
        return len(edges)

    def run_traversal(self, start_id: str, hops: int) -> Any:
        with self._driver.session() as s:
            return s.execute_read(
                lambda tx: tx.run(_CYPHER_TRAVERSAL[hops], id=start_id).single()
            )

    def run_point_lookup(self, node_id: str) -> Any:
        with self._driver.session() as s:
            return s.execute_read(
                lambda tx: tx.run("MATCH (u:User {id: $id}) RETURN u", id=node_id).single()
            )

    def run_indexed_lookup(self, min_age: int, max_age: int) -> Any:
        with self._driver.session() as s:
            return s.execute_read(
                lambda tx: tx.run(
                    "MATCH (u:User) WHERE u.age >= $lo AND u.age <= $hi RETURN count(u) AS c",
                    lo=min_age, hi=max_age,
                ).single()
            )

    def run_aggregation(self) -> Any:
        with self._driver.session() as s:
            return s.execute_read(
                lambda tx: tx.run("MATCH ()-[r:FRIEND]->() RETURN count(r) AS c").single()
            )

    def run_mixed_read(self, node_id: str) -> Any:
        return self.run_point_lookup(node_id)

    def run_mixed_write(self, src_id: str, dst_id: str) -> Any:
        with self._driver.session() as s:
            return s.execute_write(
                lambda tx: tx.run(
                    "MATCH (a:User {id: $src}), (b:User {id: $dst}) "
                    "MERGE (a)-[:FRIEND]->(b)",
                    src=src_id, dst=dst_id,
                ).consume()
            )

    def footprint(self) -> dict[str, float | None]:
        try:
            with self._driver.session() as s:
                rec = s.run(
                    "CALL dbms.queryJmx('java.lang:type=Memory') "
                    "YIELD attributes RETURN attributes"
                ).single()
                return {"stored_data_mb": None, "memory_mb": None} if rec is None else {
                    "stored_data_mb": None, "memory_mb": None,
                }
        except Exception:
            return {"stored_data_mb": None, "memory_mb": None}


class ArangoDBClient(GraphClient):
    def __init__(self, config: PlatformConfig):
        super().__init__(config)
        self._client = None
        self._db = None
        self.db_name = "benchmark"

    def connect(self) -> None:
        from arango import ArangoClient as _ArangoClient

        self._client = _ArangoClient(hosts=self.config.uri)
        sys_db = self._client.db(
            "_system", username=self.config.user,
            password=self.config.password.get_secret_value(),
        )
        if not sys_db.has_database(self.db_name):
            sys_db.create_database(self.db_name)
        self._db = self._client.db(
            self.db_name, username=self.config.user,
            password=self.config.password.get_secret_value(),
        )
        if not self._db.has_collection("users"):
            self._db.create_collection("users")
        if not self._db.has_collection("friend"):
            self._db.create_collection("friend", edge=True)
        if not self._db.has_graph("social"):
            self._db.create_graph(
                "social",
                edge_definitions=[{
                    "edge_collection": "friend",
                    "from_vertex_collections": ["users"],
                    "to_vertex_collections": ["users"],
                }],
            )

    def close(self) -> None:
        pass  # python-arango has no persistent connection to tear down

    def ensure_schema(self) -> list[str]:
        users = self._db.collection("users")
        users.add_persistent_index(fields=["ext_id"], unique=True)
        users.add_persistent_index(fields=["age"])
        return ["ext_id", "age"]

    def load_nodes(self, nodes: list[dict]) -> int:
        docs = [{"_key": n["id"], "ext_id": n["id"], "age": n["age"]} for n in nodes]
        self._db.collection("users").insert_many(docs, overwrite=True)
        return len(nodes)

    def load_edges(self, edges: list[dict]) -> int:
        docs = [
            {"_from": f"users/{e['src']}", "_to": f"users/{e['dst']}"} for e in edges
        ]
        self._db.collection("friend").insert_many(docs, overwrite=True)
        return len(edges)

    def run_traversal(self, start_id: str, hops: int) -> Any:
        aql = (
            "FOR v IN 1..@hops OUTBOUND @start friend "
            "OPTIONS {bfs: true, uniqueVertices: 'global'} "
            "COLLECT WITH COUNT INTO c RETURN c"
        )
        cursor = self._db.aql.execute(
            aql, bind_vars={"hops": hops, "start": f"users/{start_id}"}
        )
        return list(cursor)

    def run_point_lookup(self, node_id: str) -> Any:
        return self._db.collection("users").get(node_id)

    def run_indexed_lookup(self, min_age: int, max_age: int) -> Any:
        aql = "FOR u IN users FILTER u.age >= @lo AND u.age <= @hi COLLECT WITH COUNT INTO c RETURN c"
        return list(self._db.aql.execute(aql, bind_vars={"lo": min_age, "hi": max_age}))

    def run_aggregation(self) -> Any:
        aql = "FOR e IN friend COLLECT WITH COUNT INTO c RETURN c"
        return list(self._db.aql.execute(aql))

    def run_mixed_read(self, node_id: str) -> Any:
        return self.run_point_lookup(node_id)

    def run_mixed_write(self, src_id: str, dst_id: str) -> Any:
        doc = {"_from": f"users/{src_id}", "_to": f"users/{dst_id}"}
        return self._db.collection("friend").insert(doc, overwrite_mode="ignore")

    def footprint(self) -> dict[str, float | None]:
        try:
            stats = self._db.collection("users").statistics()
            size_mb = stats.get("figures", {}).get("documentsSize", 0) / (1024 * 1024)
            return {"stored_data_mb": round(size_mb, 2), "memory_mb": None}
        except Exception:
            return {"stored_data_mb": None, "memory_mb": None}


def make_client(config: PlatformConfig) -> GraphClient:
    if config.dialect == QueryDialect.AQL:
        return ArangoDBClient(config)
    return Neo4jBoltClient(config)
