# BugVault Domain Model

- **Bug Record**: a persisted troubleshooting experience containing an error,
  attempted approaches, a solution, and optional project metadata.
- **Convention Record**: a persisted project rule containing the triggering
  context, incorrect behavior, and correct behavior.
- **Retrieval**: the operation that turns a query and optional record filters
  into ranked Bug Records or Convention Records from local memory.
- **Retrieval module**: owns the Retrieval sequence: candidate collection,
  parent-record mapping, ranking, and optional Cross-Encoder refinement.
  MCP and benchmark code adapt their inputs and outputs around this module.
