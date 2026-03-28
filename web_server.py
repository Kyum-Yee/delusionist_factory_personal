#!/usr/bin/env python3
"""
Delusionist Factory — HTTP MCP Web Server

Wraps mcp_server.py (stdio) with Starlette + StreamableHTTPSessionManager
for deployment on Render (or any ASGI host).

Endpoint: POST/GET/DELETE /mcp
"""

import os
import contextlib
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

# Reuse server + all tool definitions from mcp_server.py
from mcp_server import server

# Ensure input/ exists — it is gitignored and won't exist on a fresh Render deploy
os.makedirs(os.path.join(os.path.dirname(__file__), "input"), exist_ok=True)

session_manager = StreamableHTTPSessionManager(
    app=server,
    stateless=True,  # stateless: no session persistence between requests (safe for Render restarts)
)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with session_manager.run():
        yield


app = Starlette(
    lifespan=lifespan,
    routes=[
        Mount("/mcp", app=session_manager.handle_request),
    ],
)
