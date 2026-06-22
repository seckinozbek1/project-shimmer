# ontology/

Reserved for the future cross-run **knowledge graph** and its **GNN update
engine**. This subsystem is **not yet built**: no script currently reads from
or writes to this folder, and the pipeline does not depend on it.

It is intentionally distinct from `snapshots/` (frozen per-domain state saved
via `--save-snapshot`). When implemented, this folder will hold the persistent,
cross-domain knowledge graph and the graph-neural-network state that updates it.
