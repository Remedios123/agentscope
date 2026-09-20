# -*- coding: utf-8 -*-
"""The example script to start the agent service."""
import os
import sys
from typing import ClassVar, Literal

import uvicorn
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ConfigDict, Field

from agentscope.app import create_app, SubAgentTemplate
from agentscope.app.channel import (
    DingTalkChannel,
    DiscordChannel,
    FeishuChannel,
)
from agentscope.app.hub import ClawSkillHub, GitHubMCPHub
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.rag.knowledge_base_manager import CollectionPerKbManager
from agentscope.app.storage import AsyncSQLAlchemyStorage, RedisStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.credential import (
    OpenAICredential,
    SelfConfiguredModelsMixin,
)
from agentscope.mcp import MCPClient, StdioMCPConfig, HttpMCPConfig
from agentscope.middleware import AgenticMemoryMiddleware, MiddlewareBase
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.rag import ApproxTokenChunker, QdrantStore
from agentscope.workspace import WorkspaceBase


class VolcengineCodingPlanCredential(
    SelfConfiguredModelsMixin,
    OpenAICredential,
):
    """Volcengine Ark Coding Plan through its OpenAI-compatible API.

    The available models are configured on the credential (one
    ``model_id | display name`` per line) instead of a packaged catalog.
    """

    model_config = ConfigDict(title="火山")

    type: Literal["volcengine_coding_plan_credential"] = (
        "volcengine_coding_plan_credential"
    )
    base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/coding/v3",
        description="The OpenAI-compatible Ark Coding Plan base URL.",
    )

    unsupported_parameters: ClassVar[tuple[str, ...]] = (
        "thinking_enable",
        "reasoning_effort",
        "voice",
    )

default_mcps = [
    MCPClient(
        name="browser-use",
        mcp_config=StdioMCPConfig(
            command="npx",
            args=["@playwright/mcp@latest"],
        ),
        is_stateful=True,
    ),
]

if os.getenv("AMAP_API_KEY"):
    default_mcps.append(
        MCPClient(
            name="amap",
            mcp_config=HttpMCPConfig(
                url=f"https://mcp.amap.com/mcp?key="
                f"{os.environ['AMAP_API_KEY']}",
            ),
            is_stateful=False,
        ),
    )

workspace_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "workspaces",
)
os.makedirs(workspace_dir, exist_ok=True)

if os.getenv("AGENTSCOPE_STORAGE", "sqlite").lower() == "redis":
    storage = RedisStorage(
        host="localhost",
        port=6379,
    )
else:
    # Relational storage. SQLite file by default; point
    # AGENTSCOPE_SQL_URL at a server database for deployments that need
    # one, e.g. postgresql+asyncpg://user:pass@localhost/agentscope or
    # mysql+aiomysql://user:pass@localhost/agentscope (the asyncpg /
    # aiomysql driver is installed separately). Tables auto-create on
    # first start.
    storage = AsyncSQLAlchemyStorage(
        os.getenv(
            "AGENTSCOPE_SQL_URL",
            f"sqlite+aiosqlite:///{os.path.join(workspace_dir, 'agentscope.db')}",
        ),
    )

vector_store = QdrantStore(location=":memory:")


async def longterm_memory_factory(
    user_id: str,
    agent_id: str,
    session_id: str,
    workspace: WorkspaceBase,
) -> list[MiddlewareBase]:
    """Attach Markdown-file long-term memory, stored under the session's
    workspace so it is reachable through whichever backend is bound."""
    del user_id, agent_id, session_id
    return [
        AgenticMemoryMiddleware(
            workdir=workspace.workdir,
            backend=workspace.get_backend(),
        ),
    ]


# Message bus: in-memory by default (single process; queued run
# triggers are lost on restart). Set AGENTSCOPE_BUS=redis to persist
# queued triggers and share locks across processes/restarts — requires
# a reachable Redis server and the `redis` package
# (pip install "agentscope[storage-redis]"). Optional env vars:
# AGENTSCOPE_REDIS_HOST / AGENTSCOPE_REDIS_PORT / AGENTSCOPE_REDIS_PASSWORD.
if os.getenv("AGENTSCOPE_BUS", "memory").lower() == "redis":
    from agentscope.app.message_bus import RedisMessageBus

    message_bus = RedisMessageBus(
        host=os.getenv("AGENTSCOPE_REDIS_HOST", "localhost"),
        port=int(os.getenv("AGENTSCOPE_REDIS_PORT", "6379")),
        password=os.getenv("AGENTSCOPE_REDIS_PASSWORD") or None,
    )
else:
    message_bus = InMemoryMessageBus()

app = create_app(
    storage=storage,
    message_bus=message_bus,
    extra_credentials=[VolcengineCodingPlanCredential],
    workspace_manager=LocalWorkspaceManager(
        basedir=workspace_dir,
        # The default MCP servers that will be added into the workspace
        default_mcps=default_mcps,
    ),
    # Knowledge base feature — backed by an in-memory Qdrant store. The
    # CollectionPerKbManager allocates one collection per knowledge base,
    # so any embedding dimension is allowed.
    knowledge_base_manager=CollectionPerKbManager(
        storage=storage,
        vector_store=vector_store,
    ),
    # Chunker classes users can pick from when creating a knowledge base;
    # the chosen type and parameters are pinned on the knowledge base.
    knowledge_chunkers=[ApproxTokenChunker],
    # Resource hubs the UI browses under /hub. Neither needs credentials
    # of its own — an individual MCP card declares whatever key it wants
    # from the user in its ``inputs_schema``. Passing a ClawHub token
    # only raises the rate limit.
    mcp_hubs=[GitHubMCPHub()],
    skill_hubs=[ClawSkillHub(api_token=os.getenv("CLAWHUB_API_TOKEN"))],
    # Customize your own subagent templates
    custom_subagent_templates=[
        SubAgentTemplate(
            type="explorer",
            description=(
                "Read-only agents specialized in exploration tasks. It can "
                "read files but cannot modify, create, or delete them. Use "
                "this agent type when you need to investigate the codebase, "
                "understand its structure, or gather information from files "
                "to support planning—without making any changes."
            ),
            system_prompt_template="""You are {member_name}, an explorer \
agent in team '{team_name}' led by {leader_name}.

Team purpose: {team_description}

Your role: {member_description}

## Responsibilities
- Complete the exploration tasks assigned by the team leader.
- You are read-only: you may inspect files and the codebase, but you must \
never modify, create, or delete anything.

## Reporting
- Always report the task result back to {leader_name} using the TeamSay \
tool, whether the task succeeds or fails.
- Keep your private reasoning private; only share conclusions and findings \
that the leader needs.

Note: `TeamSay` is your ONLY channel to communicate with {leader_name} and \
the other team members. Any other output you produce is invisible to them, \
so anything you want them to see MUST be sent through `TeamSay`.""",
            permission_context=PermissionContext(
                # Read-only
                mode=PermissionMode.EXPLORE,
            ),
        ),
    ],
    # Long-term memory. The default PER_AGENT workspace isolation makes
    # the memory survive across sessions of the same agent.
    extra_agent_middlewares=longterm_memory_factory,
    extra_middlewares=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
    channels=[
        DingTalkChannel,
        DiscordChannel,
        FeishuChannel,
    ],
)


if __name__ == "__main__":
    # Start the service
    uvicorn.run(
        app if sys.platform == "win32" else "main:app",
        host="0.0.0.0",
        port=8000,
        # Hot reload forces a SelectorEventLoop on Windows, which cannot
        # spawn the subprocesses that the builtin tools rely on
        reload=sys.platform != "win32",
    )
