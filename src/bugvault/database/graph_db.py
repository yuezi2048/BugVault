"""LadybugDB graph overlay — relationship layer for BugVault.

Keeps a lightweight property graph alongside the primary LanceDB store.
Records relationships that pure vector/FTS search handles poorly:

- Bug ↔ Bug (same root cause, related via tech-stack overlap)
- Bug ↔ Convention (which bug triggered which rule)
- Record ↔ TechStack / Project (categorisation edges)

The graph database is **never the primary storage** — LanceDB owns all
data. LadybugDB only stores **edges** and a thin projection of node
identity for traversal queries.

Singleton pattern: use ``get_graph_db()`` to obtain the shared instance.
"""

from __future__ import annotations

from pathlib import Path

from bugvault.config import settings
from bugvault.utils.logger import logger


# ── Singleton holder ───────────────────────────────────────────────

_graph_instance: "GraphDB | None" = None


def get_graph_db() -> "GraphDB | None":
    """Return the shared ``GraphDB`` singleton (or ``None`` on failure)."""
    global _graph_instance
    if _graph_instance is None:
        try:
            _graph_instance = GraphDB()
            _graph_instance.initialize()
        except Exception:
            logger.exception("Failed to initialise LadybugDB graph (non-fatal)")
            return None
    return _graph_instance


# ===================================================================
#  Schema DDL — run once at init
# ===================================================================

_NODE_TABLES = [
    "CREATE NODE TABLE IF NOT EXISTS Bug("
    "  record_id STRING,"
    "  bug_title STRING,"
    "  root_cause STRING,"
    "  tech_stack STRING,"
    "  project_name STRING,"
    "  create_time STRING,"
    "  PRIMARY KEY (record_id)"
    ")",
    "CREATE NODE TABLE IF NOT EXISTS Convention("
    "  record_id STRING,"
    "  convention_name STRING,"
    "  scope STRING,"
    "  tags STRING,"
    "  create_time STRING,"
    "  PRIMARY KEY (record_id)"
    ")",
    "CREATE NODE TABLE IF NOT EXISTS TechStack("
    "  name STRING,"
    "  PRIMARY KEY (name)"
    ")",
    "CREATE NODE TABLE IF NOT EXISTS Project("
    "  name STRING,"
    "  PRIMARY KEY (name)"
    ")",
    "CREATE NODE TABLE IF NOT EXISTS RootCause("
    "  pattern STRING,"
    "  PRIMARY KEY (pattern)"
    ")",
]

_REL_TABLES = [
    # Bug-to-Bug same root cause
    "CREATE REL TABLE IF NOT EXISTS SAME_ROOT_CAUSE("
    "  FROM Bug TO Bug"
    ")",
    # Bug-to-TechStack
    "CREATE REL TABLE IF NOT EXISTS HAS_TECH_STACK("
    "  FROM Bug TO TechStack"
    ")",
    "CREATE REL TABLE IF NOT EXISTS CONVENTION_HAS_TECH_STACK("
    "  FROM Convention TO TechStack"
    ")",
    # Bug/Convention-to-Project
    "CREATE REL TABLE IF NOT EXISTS BELONGS_TO("
    "  FROM Bug TO Project"
    ")",
    "CREATE REL TABLE IF NOT EXISTS CONVENTION_BELONGS_TO("
    "  FROM Convention TO Project"
    ")",
    # Bug-to-Convention (which bug triggered which rule)
    "CREATE REL TABLE IF NOT EXISTS TRIGGERED("
    "  FROM Bug TO Convention"
    ")",
    # Bug-to-Bug similarity (discovered via RRF/Cross-Encoder)
    "CREATE REL TABLE IF NOT EXISTS RELATED_TO("
    "  FROM Bug TO Bug,"
    "  score DOUBLE"
    ")",
]


# ===================================================================
#  GraphDB
# ===================================================================


class GraphDB:
    """Wrapper around a LadybugDB connection for graph overlay operations.

    Usage
    -----
        gdb = GraphDB()
        gdb.initialize()
        gdb.ensure_bug({"record_id": "...", "bug_title": "...", ...})
        gdb.link_bug_to_tech_stack(bug_id, "Python")
    """

    def __init__(self) -> None:
        self._conn = None
        self._db_path: Path | None = None

    # ── Lifecycle ───────────────────────────────────────────────────

    def initialize(self) -> None:
        """Open (or create) the LadybugDB database and apply the schema."""
        import ladybug as lb

        db_dir = settings.data_root / "graph"
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = db_dir / "bugvault_graph.lbdb"

        database = lb.Database(str(self._db_path))
        self._conn = lb.Connection(database)

        # Apply DDL — IF NOT EXISTS makes this idempotent
        for ddl in _NODE_TABLES:
            self._conn.execute(ddl)
        for ddl in _REL_TABLES:
            self._conn.execute(ddl)

        logger.info("GraphDB ready at %s", self._db_path)

    @property
    def is_ready(self) -> bool:
        return self._conn is not None

    # ── Node ensure / merge ────────────────────────────────────────

    def ensure_bug(self, record: dict) -> None:
        """Create or update a ``Bug`` node from a LanceDB table row."""
        self._conn.execute(
            "MERGE (b:Bug {record_id: $record_id}) "
            "SET b.bug_title = $bug_title, "
            "    b.root_cause = $root_cause, "
            "    b.tech_stack = $tech_stack, "
            "    b.project_name = $project_name, "
            "    b.create_time = $create_time",
            {
                "record_id": record.get("record_id", ""),
                "bug_title": record.get("bug_title", ""),
                "root_cause": record.get("root_cause", ""),
                "tech_stack": record.get("tech_stack", ""),
                "project_name": record.get("project_name", ""),
                "create_time": record.get("create_time", ""),
            },
        )

    def ensure_convention(self, record: dict) -> None:
        """Create or update a ``Convention`` node from a LanceDB table row."""
        self._conn.execute(
            "MERGE (c:Convention {record_id: $record_id}) "
            "SET c.convention_name = $convention_name, "
            "    c.scope = $scope, "
            "    c.tags = $tags, "
            "    c.create_time = $create_time",
            {
                "record_id": record.get("record_id", ""),
                "convention_name": record.get("bug_title", ""),
                "scope": record.get("project_name", ""),
                "tags": record.get("tech_stack", ""),
                "create_time": record.get("create_time", ""),
            },
        )

    def ensure_tech_stack(self, name: str) -> None:
        """Create a ``TechStack`` node if it doesn't exist."""
        self._conn.execute(
            "MERGE (t:TechStack {name: $name})",
            {"name": name},
        )

    def ensure_project(self, name: str) -> None:
        """Create a ``Project`` node if it doesn't exist."""
        self._conn.execute(
            "MERGE (p:Project {name: $name})",
            {"name": name},
        )

    # ── Edge creation ──────────────────────────────────────────────

    def link_bug_to_tech_stack(self, bug_id: str, tech_name: str) -> None:
        """Link a Bug node to a TechStack node."""
        self._conn.execute(
            "MATCH (b:Bug {record_id: $bug_id}), (t:TechStack {name: $tech_name}) "
            "MERGE (b)-[:HAS_TECH_STACK]->(t)",
            {"bug_id": bug_id, "tech_name": tech_name},
        )

    def link_convention_to_tech_stack(self, convention_id: str, tech_name: str) -> None:
        """Link a Convention node to a TechStack node."""
        self._conn.execute(
            "MATCH (c:Convention {record_id: $cid}), (t:TechStack {name: $tech_name}) "
            "MERGE (c)-[:CONVENTION_HAS_TECH_STACK]->(t)",
            {"cid": convention_id, "tech_name": tech_name},
        )

    def link_bug_to_project(self, bug_id: str, project_name: str) -> None:
        """Link a Bug node to a Project node."""
        self._conn.execute(
            "MATCH (b:Bug {record_id: $bug_id}), (p:Project {name: $pname}) "
            "MERGE (b)-[:BELONGS_TO]->(p)",
            {"bug_id": bug_id, "pname": project_name},
        )

    def link_convention_to_project(self, convention_id: str, project_name: str) -> None:
        """Link a Convention node to a Project node."""
        self._conn.execute(
            "MATCH (c:Convention {record_id: $cid}), (p:Project {name: $pname}) "
            "MERGE (c)-[:CONVENTION_BELONGS_TO]->(p)",
            {"cid": convention_id, "pname": project_name},
        )

    def link_same_root_cause(self, bug_id_a: str, bug_id_b: str) -> None:
        """Create a bidirectional SAME_ROOT_CAUSE edge between two Bug nodes."""
        self._conn.execute(
            "MATCH (a:Bug {record_id: $a}), (b:Bug {record_id: $b}) "
            "MERGE (a)-[:SAME_ROOT_CAUSE]->(b) "
            "MERGE (b)-[:SAME_ROOT_CAUSE]->(a)",
            {"a": bug_id_a, "b": bug_id_b},
        )

    def link_triggered(self, bug_id: str, convention_id: str) -> None:
        """Link a Bug to a Convention it triggered."""
        self._conn.execute(
            "MATCH (b:Bug {record_id: $bug_id}), (c:Convention {record_id: $cid}) "
            "MERGE (b)-[:TRIGGERED]->(c)",
            {"bug_id": bug_id, "cid": convention_id},
        )

    def link_related(self, bug_id_a: str, bug_id_b: str, score: float = 0.5) -> None:
        """Create a bidirectional RELATED_TO edge with similarity score."""
        self._conn.execute(
            "MATCH (a:Bug {record_id: $a}), (b:Bug {record_id: $b}) "
            "MERGE (a)-[:RELATED_TO {score: $score}]->(b) "
            "MERGE (b)-[:RELATED_TO {score: $score}]->(a)",
            {"a": bug_id_a, "b": bug_id_b, "score": score},
        )

    # ── Query helpers ──────────────────────────────────────────────

    def find_related_bugs(
        self, record_id: str, max_hops: int = 2,
    ) -> list[dict]:
        """Traverse the graph from a Bug and return related records.

        Uses Cypher variable-length path matching to find bugs that
        share root causes, tech stacks, or are explicitly linked.

        Args:
            record_id: Starting Bug node.
            max_hops: Maximum traversal depth (default 2).

        Returns:
            List of dicts with ``record_id`` and ``bug_title``.
        """
        if self._conn is None:
            return []

        # LadybugDB requires literal hop counts (not parameterised)
        hop_count = min(max_hops, 3)
        query = (
            f"MATCH (b:Bug {{record_id: $record_id}})"
            f"-[*1..{hop_count}]-(related:Bug) "
            f"WHERE related.record_id <> $record_id "
            f"RETURN DISTINCT related.record_id AS record_id, "
            f"       related.bug_title AS bug_title "
            f"LIMIT 20"
        )
        try:
            result = self._conn.execute(
                query,
                {"record_id": record_id},
            )
            df = result.get_as_df()
            if df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception:
            logger.exception("Graph query failed (non-fatal)")
            return []

    def find_bugs_by_tech_stack(self, tech: str) -> list[dict]:
        """Find all Bug nodes that use a particular technology."""
        if self._conn is None:
            return []
        query = (
            "MATCH (b:Bug)-[:HAS_TECH_STACK]->(t:TechStack {name: $tech}) "
            "RETURN b.record_id AS record_id, b.bug_title AS bug_title"
        )
        try:
            result = self._conn.execute(query, {"tech": tech})
            df = result.get_as_df()
            if df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception:
            logger.exception("Graph query failed (non-fatal)")
            return []

    def find_conventions_for_bug(self, bug_id: str) -> list[dict]:
        """Find all Convention nodes triggered by a Bug."""
        if self._conn is None:
            return []
        query = (
            "MATCH (b:Bug {record_id: $bug_id})-[:TRIGGERED]->(c:Convention) "
            "RETURN c.record_id AS record_id, c.convention_name AS convention_name"
        )
        try:
            result = self._conn.execute(query, {"bug_id": bug_id})
            df = result.get_as_df()
            if df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception:
            logger.exception("Graph query failed (non-fatal)")
            return []

    def find_bugs_with_same_root_cause(self, root_cause: str) -> list[dict]:
        """Find Bug nodes whose root_cause field matches a pattern."""
        if self._conn is None:
            return []
        query = (
            "MATCH (b:Bug) "
            "WHERE b.root_cause CONTAINS $pattern "
            "RETURN b.record_id AS record_id, b.bug_title AS bug_title"
        )
        try:
            result = self._conn.execute(query, {"pattern": root_cause})
            df = result.get_as_df()
            if df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception:
            logger.exception("Graph query failed (non-fatal)")
            return []


# ===================================================================
#  Convenience: write all edges for a BugRecord
# ===================================================================


def write_bug_graph_edges(gdb: GraphDB, record: dict) -> None:
    """Create all graph nodes and edges for a single bug record.

    Called from the save pipeline after LanceDB write succeeds.
    All failures are non-fatal — logged but not propagated.
    """
    if gdb is None or not gdb.is_ready:
        return

    try:
        record_id = record.get("record_id", "")
        if not record_id:
            return

        # 1. Ensure the Bug node exists
        gdb.ensure_bug(record)

        # 2. Link to TechStack nodes
        tech_stack_raw = record.get("tech_stack", "") or ""
        for tech in [t.strip() for t in tech_stack_raw.split(",") if t.strip()]:
            gdb.ensure_tech_stack(tech)
            gdb.link_bug_to_tech_stack(record_id, tech)

        # 3. Link to Project node
        project_name = record.get("project_name", "") or ""
        if project_name:
            gdb.ensure_project(project_name)
            gdb.link_bug_to_project(record_id, project_name)

    except Exception:
        logger.exception("Failed to write graph edges for record %s (non-fatal)", record.get("record_id", "?"))


def write_convention_graph_edges(gdb: GraphDB, record: dict) -> None:
    """Create all graph nodes and edges for a convention record."""
    if gdb is None or not gdb.is_ready:
        return

    try:
        record_id = record.get("record_id", "")
        if not record_id:
            return

        # 1. Ensure the Convention node exists
        gdb.ensure_convention(record)

        # 2. Link to TechStack nodes (stored in tags field)
        tags_raw = record.get("tech_stack", "") or ""
        for tag in [t.strip() for t in tags_raw.split(",") if t.strip()]:
            gdb.ensure_tech_stack(tag)
            gdb.link_convention_to_tech_stack(record_id, tag)

        # 3. Link to Project node (stored in scope/name field)
        scope_name = record.get("project_name", "") or ""
        if scope_name:
            gdb.ensure_project(scope_name)
            gdb.link_convention_to_project(record_id, scope_name)

    except Exception:
        logger.exception("Failed to write graph edges for convention %s (non-fatal)", record.get("record_id", "?"))
