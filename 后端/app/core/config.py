"""Application configuration.

All runtime values are read from environment variables / the project `.env`
file via Pydantic Settings. Business code must never hardcode hosts, IPs,
AppKeys, model names, URLs, timeouts or full resource URLs (see
《后端技术栈与全局规范》一). Only `.env.example` is committed; the real `.env`
is git-ignored.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed view over all configuration.

    Defaults here are deployment-neutral fallbacks only (host/port, public
    static paths, neutral base URLs from the specs); no business secrets or
    private hosts are baked in.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # —— Server ——
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    # Comma-separated origins; parsed by `frontend_origins_list`.
    FRONTEND_ORIGINS: str = "http://localhost:3000"
    # Reserved for future scenarios that truly need public URLs; must stay
    # empty for the current phase (no full URL is ever persisted).
    PUBLIC_BASE_URL: str = ""

    # —— Persistence ——
    DATABASE_URL: str = "sqlite:///./data/lvyousuotu.db"

    # —— Auth / single-user demo ——
    DEFAULT_USER_ID: str = "demo_user_001"

    # —— Static storage ——
    STATIC_ROOT: str = "./static"
    # Generated-image downloads are denied unless the HTTPS host matches one
    # of these exact hosts or dot-prefixed suffixes. Keep this deployment
    # configurable because provider temporary object-storage hosts can change.
    GENERATED_IMAGE_ALLOWED_HOSTS: str = ".volces.com,.volccdn.com"
    GENERATED_IMAGE_MAX_BYTES: int = 20 * 1024 * 1024
    GENERATED_IMAGE_MAX_PIXELS: int = 40_000_000
    MEMORY_TOMBSTONE_SECRET: str = "lvyousuotu-demo-change-in-production"

    # —— 火山方舟 Agent Plan：文本、图片理解与 Seedream 图片生成 ——
    ARK_PLAN_API_KEY: str = ""
    ARK_PLAN_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/plan/v3"
    ARK_CHAT_MODEL: str = "doubao-seed-evolving"
    ARK_TEXT_TIMEOUT_SECONDS: int = 120
    ARK_IMAGE_MODEL: str = "doubao-seedream-5-0-pro-260628"
    ARK_IMAGE_SIZE: str = "2K"
    # 行程规划（FC + plain JSON）单独更长超时：prompt 大且开启深度思考。
    DEEPSEEK_PLANNING_TIMEOUT_SECONDS: int = 120
    ARK_IMAGE_TIMEOUT_SECONDS: int = 120
    MODEL_MAX_RETRY: int = 1
    MODEL_RETRY_BACKOFF_SECONDS: float = 1.0
    # —— DeepSeek OpenAI-compatible planning models ——
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_CHAT_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_FLASH_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_PRO_MODEL: str = "deepseek-v4-pro"
    PHOTO_ANALYZE_PARALLELISM: int = 5
    GENERATION_FILE_IO_PARALLELISM: int = 4
    GENERATION_IMAGE_PARALLELISM: int = 2

    # —— Tool chain master switches （见《外部事实源与工具调用规范》六）——
    TOOLS_ENABLED: bool = True

    # —— 高德 ——
    AMAP_API_KEY: str = ""
    AMAP_BASE_URL: str = "https://restapi.amap.com"
    AMAP_MCP_ENABLED: bool = True
    AMAP_MCP_SSE_URL: str = "https://mcp.amap.com/sse"
    AMAP_MAX_QPS: int = 3

    # —— 飞友 TripMatch MCP（空铁联运、火车票、车站）——
    # Tripmatch 官方文档给出的服务路径大小写有误；实际可达路径为 lowercase。
    VARIFLIGHT_TRIPMATCH_MCP_ENABLED: bool = True
    VARIFLIGHT_TRIPMATCH_MCP_URL: str = (
        "https://ai.variflight.com/servers/tripmatch/mcp/"
    )
    # Tripmatch 与 Aviation 共用；仅在运行时 URL query 中传给上游，禁止记录。
    VARIFLIGHT_API_KEY: str = ""
    VARIFLIGHT_TRIPMATCH_TIMEOUT_SECONDS: int = 30

    # —— 飞友 Aviation MCP（直飞、纯航班中转、航线方案）——
    VARIFLIGHT_AVIATION_MCP_ENABLED: bool = True
    VARIFLIGHT_AVIATION_MCP_URL: str = (
        "https://ai.variflight.com/servers/aviation/mcp/"
    )
    VARIFLIGHT_AVIATION_TIMEOUT_SECONDS: int = 30

    # —— 工具通用超时/重试 ——
    TOOL_TIMEOUT_SECONDS: int = 20
    TOOL_MAX_RETRY: int = 1

    @property
    def frontend_origins_list(self) -> list[str]:
        """Parse `FRONTEND_ORIGINS` into a clean list for CORS."""
        return [
            origin.strip()
            for origin in self.FRONTEND_ORIGINS.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached `Settings` instance."""
    return Settings()


settings = get_settings()
