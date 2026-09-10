# BugVault Domain Model

- **Memory assets**: BugVault's durable domain knowledge consists of Bug Records and Convention Records. Prevention rules are derived output written for an agent client, not a third first-class record type.
- **Bug Record**: a persisted troubleshooting experience containing an error,
  attempted approaches, a solution, and optional project metadata.
- **Convention Record**: a persisted project rule containing the triggering
  context, incorrect behavior, and correct behavior. It may be captured from
  a user correction or stated proactively, and is intended to apply repeatedly.
- **Prevention rule**: a derived, agent-facing rule produced by reflection and
  written to a client instruction file such as `CLAUDE.md`; it is not a
  separate BugVault memory asset.
- **Archive**: the complete, human-readable persisted copy of a memory record.
- **Index projection**: a storage representation derived from a complete
  record for a specific query technology, such as LanceDB vectors/chunks or a
  Graph relationship projection; it is not itself the domain record.
- **Reflection**: the operation that derives an agent-facing prevention rule
  from a known misunderstanding or repeated failure; it does not implicitly
  create another Bug Record.
- **BugVault boundary**: BugVault saves, retrieves, and reflects project memory;
  the MCP client decides whether to follow retrieved guidance, and BugVault
  does not plan work, edit business code, or run an agent loop.
- **Retrieval**: the operation that turns a query and optional record filters
  into ranked Bug Records or Convention Records from local memory.
- **Retrieval module**: owns the Retrieval sequence: candidate collection,
  parent-record mapping, ranking, and optional Cross-Encoder refinement.
  MCP and benchmark code adapt their inputs and outputs around this module.
- **Typed retrieval**: each retrieval action returns either Bug Records or
  Convention Records, selected by the caller; the shared pipeline does not
  imply mixed-type results.
- **Record persistence**: the lifecycle that validates a Bug Record or
  Convention Record, archives a complete record, batches parent and chunk
  embeddings, writes local memory, and projects relationships into Graph.
- **Record persistence module**: owns that lifecycle. MCP adapts its outcome
  into a success, draft, or validation message; Archive, LanceDB, and Graph
  adapt their storage work behind the module.
- **Project name vs scope**: `project_name` identifies the project a record
  belongs to; Convention `scope` identifies where or under which boundary the
  rule applies. They are distinct concepts even when the storage schema
  temporarily reuses a column.
- **Convention scope**: the applicability boundary of a Convention, covering
  code paths, modules, subsystems, API surfaces, or the whole project. It is
  distinct from `trigger_context` (when the rule matters) and `tags` (how the
  rule is classified).
- **`project-wide`**: the canonical scope value for a Convention that applies
  across the whole project.
- **Record identity**: the domain key used to decide whether a save updates an
  existing record or creates a distinct one; semantic similarity alone does
  not establish identity.
- **Draft**: an incomplete save request awaiting required fields. A draft is
  not archived or retrievable as a memory record.
- **Record establishment**: a complete record becomes a formal memory after
  validation and successful Archive write. Vector and Graph projections are
  eventually consistent and may lag or fail without invalidating the record.
- **Empty retrieval**: a valid query with no matching records is a normal empty
  result, distinct from validation or storage failure.
- **RAG evaluation**: an optional quality assessment attached to retrieval; it
  does not create, remove, or redefine records, and may degrade independently.

## Documentation lineage

- **`codex-docs/`**: the renamed historical `docs/` tree, including its agent,
  reference, review, test, and version records. Its content is preserved; only
  links and provenance markers may be adjusted.
- **`reasonix-doc/`**: historical development traces produced while working
  with the Reasonix agent, retained as provenance rather than current project
  truth.
- **`docs/`**: the home for newly created, current project documentation. It is
  authoritative for current project facts after the historical tree moves.
