"""
The customer_service function package.

Imports nothing on purpose. `packages.registry` walks this directory to read
`manifest.yaml` and `seeds.yaml` without importing `task.py`, which would pull in
the Anthropic client. See `packages/__init__.py`.
"""
