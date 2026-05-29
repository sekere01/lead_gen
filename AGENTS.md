## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

**CRITICAL: For ANY codebase question, automatically use graphify first — do NOT wait for the user to ask.**

- Run `graphify query "<question>"` to answer codebase questions (returns a scoped subgraph, much smaller than raw grep)
- Use `graphify path "<A>" "<B>"` for relationship queries between symbols
- Use `graphify explain "<concept>"` for focused concept analysis with neighbors
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review
- Run `graphify update .` to keep the graph current after code changes (AST-only, no API cost)
