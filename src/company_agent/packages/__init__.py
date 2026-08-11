"""
Function packages.

A function package is one directory holding everything a capability needs:
its intent seeds, its task module, its policy/prompt copy, its write-action
manifest and its eval cases. Adding a capability means adding a directory —
never editing a central dispatch table.

**This module must never import anything.** It is the anchor of the boundary
that keeps `packages.registry` pure: rag-api and the intent seeder both read
package manifests and seeds, and neither may pull in the Anthropic client that
`agent_core.llm.anthropic` imports at module scope. Only `packages.registrar`
imports a task module, and only agent-core calls it.

`tests/test_package_boundary.py` enforces this in a subprocess.
"""
