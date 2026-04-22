"""Curated infrastructure templates dropped into build dirs pre-Wave-B.

Each template lives in its own subpackage (e.g. ``pnpm_monorepo/``) and is
resolved by name through :mod:`agent_team_v15.template_renderer`. The files
below are shipped as package data so ``importlib.resources`` can read them
in both editable and installed modes.
"""
