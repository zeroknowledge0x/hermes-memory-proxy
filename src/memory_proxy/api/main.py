"""FastAPI app — OpenAI-compatible endpoints. No business logic here;
delegates to the orchestrator."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from memory_proxy.pipeline.orchestrator import Orchestrator
from memory_proxy.providers.openai_compatible_adapter import OpenAICompatibleAdapter


def create_app(orchestrator: Orchestrator | None = None) -> FastAPI:
    app = FastAPI(title="memory-proxy", version="0.1.0")
    app.state.orchestrator = orchestrator

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/admin/reload-identity")
    async def reload_identity():
        orch: Orchestrator = app.state.orchestrator
        if orch and orch._identity:
            orch._identity.reload()
            return {"status": "reloaded"}
        return {"status": "no-identity"}

    @app.get("/v1/models")
    async def models():
        # Proxy the model list from the REAL upstream (Nous/etc) so Hermes
        # sees the actual available models instead of an empty list.
        orch: Orchestrator = app.state.orchestrator
        try:
            data = await orch._provider.list_models()
            return {"object": "list", "data": data}
        except Exception:
            return {"object": "list", "data": []}

    @app.get("/v1/models/{model}")
    async def model_detail(model: str):
        # Proxy to upstream; fall back to an echo if upstream has no detail.
        orch: Orchestrator = app.state.orchestrator
        try:
            detail = await orch._provider.get_model(model)
            if detail:
                return detail
        except Exception:
            pass
        return {
            "id": model,
            "object": "model",
            "created": 0,
            "owned_by": "memory-proxy",
            "root": model,
        }

    @app.post("/v1/memory")
    async def post_memory(payload: dict, user: str = ""):
        """Write a fact directly (programmatic memory, no LLM forward needed).

        Body: {"content": "fact text", "source": "optional"}.
        Returns {"status": "ok", "id": "..."} or {"status": "duplicate"}.
        """
        orch: Orchestrator = app.state.orchestrator
        if not orch or not orch._memory:
            return {"status": "no-memory"}
        uid = orch._resolve_user_id({"user": user}) if user else str(orch._default_user_id)
        content = (payload.get("content") or "").strip()
        if not content:
            return {"status": "error", "error": "content required"}
        try:
            fact_id = await orch._memory.add_fact(uid, content, payload.get("source"))
            if fact_id is None:
                return {"status": "duplicate"}
            return {"status": "ok", "id": fact_id}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    @app.get("/v1/memory")
    async def get_memory(user: str = "", limit: int = 10, q: str = ""):
        """External memory retrieval for the Hermes plugin (Future Plan #2).

        Returns ranked facts + identity so the plugin can inject them into
        the system prompt. `user` is the opaque Hermes id (e.g. 'telegram:...');
        the orchestrator hashes it to a UUID.

        Optional `q` = semantic query (user's latest message). When empty,
        falls back to a profile-style probe so important durable facts surface.
        """
        orch: Orchestrator = app.state.orchestrator
        if not orch or not orch._memory:
            return {"memory": [], "identity": {}}
        uid = orch._resolve_user_id({"user": user}) if user else str(orch._default_user_id)
        try:
            limit = max(1, min(limit, 50))
            query = (q or "").strip() or (
                "user name preferences identity rules language environment"
            )
            # Primary: query-aware semantic retrieval
            hits = await orch._memory.search(uid, query, limit=limit)
            # Diversity: if query was specific, also pull a couple of high-importance
            # profile facts so identity never drops off the injection block.
            if q and limit >= 4:
                profile_hits = await orch._memory.search(
                    uid,
                    "nama preferensi aturan bahasa identitas user",
                    limit=min(3, limit // 2),
                )
                seen = {h["content"] for h in hits}
                for ph in profile_hits:
                    if ph["content"] not in seen:
                        hits.append(ph)
                        seen.add(ph["content"])
                hits = hits[:limit]
            identity = {}
            if orch._identity:
                identity = {
                    "soul": orch._identity.soul,
                    "user": orch._identity.user,
                }
            return {
                "memory": [h["content"] for h in hits],
                "identity": identity,
                "query_used": query,
                "count": len(hits),
            }
        except Exception:
            return {"memory": [], "identity": {}}

    @app.post("/v1/admin/dedupe")
    async def admin_dedupe(user: str = ""):
        """One-shot / on-demand cleanup: expire exact-text duplicates and
        keep only the newest consolidated profile per user."""
        orch: Orchestrator = app.state.orchestrator
        if not orch or not orch._memory:
            return {"status": "no-memory"}
        try:
            if user:
                uid = orch._resolve_user_id({"user": user})
                n_exact = await orch._memory.expire_exact_duplicates(uid)
                n_cons = await orch._memory.expire_old_consolidated(uid, keep=1)
            else:
                n_exact = await orch._memory.expire_exact_duplicates(None)
                # expire old consolidated for every user that has any
                n_cons = 0
                # lightweight: only known telegram default user + default uuid
                for uid in (
                    str(orch._default_user_id),
                    orch._resolve_user_id({"user": "telegram:5398668166"}),
                ):
                    n_cons += await orch._memory.expire_old_consolidated(uid, keep=1)
            return {
                "status": "ok",
                "expired_exact_dupes": n_exact,
                "expired_old_consolidated": n_cons,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    @app.post("/v1/consolidate")
    async def consolidate(user: str = "", keep: int = 20):
        """Time-based loop endpoint (Future Plan #2 / D-023).

        Promotes recent facts into a consolidated Long memory via LLM summary.
        Called by a Hermes cron job with a FLAT prompt (never brain_loop()).
        """
        orch: Orchestrator = app.state.orchestrator
        if not orch or not orch._memory:
            return {"status": "no-memory"}
        uid = orch._resolve_user_id({"user": user}) if user else str(orch._default_user_id)
        try:
            return await orch.consolidate(uid, keep=keep)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    @app.post("/v1/reflect")
    async def reflect(user: str = ""):
        """Time-based loop endpoint (D-023). Score importance of recent facts."""
        orch: Orchestrator = app.state.orchestrator
        if not orch or not orch._memory:
            return {"status": "no-memory"}
        uid = orch._resolve_user_id({"user": user}) if user else str(orch._default_user_id)
        try:
            return await orch.reflect(uid)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    @app.post("/v1/audit")
    async def audit(user: str = "", since_hours: int = 24):
        """Daily audit loop (Opsi C): sift conversations -> promote useful,
        archive the rest. Called by a Hermes cron job with a FLAT prompt."""
        orch: Orchestrator = app.state.orchestrator
        if not orch or not orch._memory:
            return {"status": "no-memory"}
        uid = orch._resolve_user_id({"user": user}) if user else str(orch._default_user_id)
        try:
            return await orch.audit(uid, since_hours=since_hours)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        payload = await request.json()
        orch: Orchestrator = app.state.orchestrator
        result = await orch.handle(payload)
        if payload.get("stream"):
            return StreamingResponse(result, media_type="text/event-stream")
        return JSONResponse(result)

    return app


def build_default_app() -> FastAPI:
    """Wire the app from settings. Async resources (DB pool, writer worker)
    are initialised in the lifespan handler, not at import/build time."""
    from memory_proxy.config.settings import load_settings
    from memory_proxy.context.budgeter import TokenBudgeter
    from memory_proxy.identity.loader import IdentityLoader
    from memory_proxy.knowledge.embedding import EmbeddingService
    from memory_proxy.knowledge.repository import KnowledgeRepository
    from memory_proxy.memory.repository import MemoryRepository
    from memory_proxy.memory.conversation_repo import ConversationRepository
    from memory_proxy.memory.writer import MemoryWriter
    from memory_proxy.providers.factory import build_provider, build_credentials
    from memory_proxy.api.security import install_security
    from memory_proxy.storage.db import init_pool, close_pool

    settings = load_settings()

    app = create_app(None)
    # Security: auth + rate limit (Phase 3). Active per env config.
    install_security(
        app,
        auth_token=settings.auth_token,
        rate_limit_per_min=settings.rate_limit_per_min,
        bind_host=settings.bind_host,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # --- startup ---
        pool = await init_pool(settings.database_url)
        embedder = EmbeddingService(settings.embedding_model, settings.embedding_dim)
        identity = IdentityLoader("identity")
        identity.load()

        provider = build_provider(
            settings.provider_type, settings.upstream_base_url,
            build_credentials(
                api_key=settings.upstream_api_key,
                oauth_file=settings.nous_auth_file,
            ),
        )
        extractor = None  # wire a real LLM extractor here when enabled
        if settings.extraction_enabled:
            from memory_proxy.memory.llm_extractor import LLMFactExtractor
            extractor = LLMFactExtractor(
                base_url=settings.upstream_base_url,
                credentials=build_credentials(
                    api_key=settings.upstream_api_key,
                    oauth_file=settings.nous_auth_file,
                ),
                model=settings.extraction_model,
            )
        mem_repo = MemoryRepository(pool, embedder)
        conv_repo = ConversationRepository(pool, embedder)
        writer = MemoryWriter(mem_repo, extractor, enabled=settings.extraction_enabled)
        writer.start()

        app.state.orchestrator = Orchestrator(
            provider,
            identity=identity,
            memory_repo=mem_repo,
            knowledge_repo=KnowledgeRepository(pool, embedder),
            conversation_repo=conv_repo,
            writer=writer,
            budgeter=TokenBudgeter(settings.context_window, settings.reserved_pct),
            default_user_id=settings.default_user_id,
            single_user_mode=settings.single_user_mode,
        )
        yield
        # --- shutdown ---
        await writer.stop()
        await close_pool()

    app = create_app(None)
    app.router.lifespan_context = lifespan
    return app
