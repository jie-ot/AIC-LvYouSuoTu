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
    # Optional deployment-provided CJK font. If absent, renderer probes common
    # OFL Noto/Source Han installations and otherwise emits a text-free card.
    POSTCARD_FONT_PATH: str = ""
    POSTCARD_AESTHETIC_REVIEW_ENABLED: bool = True
    POSTCARD_AESTHETIC_REPAIR_ENABLED: bool = True
    POSTCARD_AESTHETIC_MIN_SCORE: int = 7
    MEMORY_TOMBSTONE_SECRET: str = "lvyousuotu-demo-change-in-production"

    # —— 火山方舟 Agent Plan：文本 / 图片理解，密钥与按量 API 分开 ——
    ARK_PLAN_API_KEY: str = ""
    ARK_PLAN_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/plan/v3"
    ARK_CHAT_MODEL: str = "doubao-seed-2.1-turbo"
    ARK_TEXT_TIMEOUT_SECONDS: int = 120
    # —— 火山方舟普通按量 API：Seedream 图片生成 ——
    ARK_IMAGE_API_KEY: str = ""
    ARK_IMAGE_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    ARK_IMAGE_MODEL: str = "doubao-seedream-5-0-pro-260628"
    ARK_IMAGE_FALLBACK_MODELS: str = "doubao-seedream-5-0-260128"
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

    # —— A 类：高德 ——
    AMAP_API_KEY: str = ""
    AMAP_BASE_URL: str = "https://restapi.amap.com"
    AMAP_MCP_ENABLED: bool = True
    AMAP_MCP_SSE_URL: str = "https://mcp.amap.com/sse"
    AMAP_MAX_QPS: int = 3

    # —— A 类：和风天气（可选）——
    QWEATHER_API_KEY: str = ""
    QWEATHER_BASE_URL: str = "https://devapi.qweather.com"

    # —— A′ 类：社区铁路 MCP（失败静默降级 B）——
    RAIL_MCP_ENABLED: bool = True
    RAIL_MCP_ENDPOINT: str = "stdio:npx -y 12306-mcp"

    # —— A′ 类：飞友 Tripmatch MCP（航班与空铁中转候选）——
    # Tripmatch 官方文档给出的服务路径大小写有误；实际可达路径为 lowercase。
    VARIFLIGHT_TRIPMATCH_MCP_ENABLED: bool = True
    VARIFLIGHT_TRIPMATCH_MCP_URL: str = (
        "https://ai.variflight.com/servers/tripmatch/mcp/"
    )
    # Tripmatch 与 Aviation 共用；仅在运行时 URL query 中传给上游，禁止记录。
    VARIFLIGHT_API_KEY: str = ""
    VARIFLIGHT_TRIPMATCH_TIMEOUT_SECONDS: int = 30

    # —— A′ 类：飞友 Aviation MCP（纯航班中转）——
    VARIFLIGHT_AVIATION_MCP_ENABLED: bool = True
    VARIFLIGHT_AVIATION_MCP_URL: str = (
        "https://ai.variflight.com/servers/aviation/mcp/"
    )
    VARIFLIGHT_AVIATION_TIMEOUT_SECONDS: int = 30

    # —— 工具通用超时/重试 ——
    TOOL_TIMEOUT_SECONDS: int = 20
    TOOL_MAX_RETRY: int = 1

    # —— A′ 社区 MCP 运行时（持久会话 + 非阻塞冷启动；防止请求线程被子进程冷启动阻塞）——
    # 后台建立/初始化 MCP 会话的最长等待（含 npx/uvx 首次拉包冷启动），仅在后台线程消耗，不阻塞请求线程。
    MCP_STARTUP_TIMEOUT_SECONDS: int = 60
    # 后端启动完成前等待已启用 MCP 进入 ready/failed，避免首个请求因冷启动误降级。
    MCP_WAIT_READY_ON_STARTUP: bool = True
    # MCP 端点建立/调用失败后，在该时间窗内视为不可用并直接降级 B，避免反复冷启动阻塞。
    MCP_UNAVAILABLE_TTL_SECONDS: int = 120

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
