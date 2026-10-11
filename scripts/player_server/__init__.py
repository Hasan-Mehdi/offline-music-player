"""Reusable building blocks for the local music-player HTTP server.

The package is intentionally small: ``scripts.server`` remains the public Flask
module, while pure retrieval helpers live here so they can be tested and reused
without importing the whole application.
"""

