"""读取环境变量和 YAML 配置。"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]


class DouyinSettings(BaseModel):
    """抖音采集服务连接配置。"""
    enabled: bool = True
    room_id: str = ""
    ws_url: str = "ws://127.0.0.1:1088"
    reconnect_seconds: int = 5


class ViduSettings(BaseModel):
    """Vidu 页面连接配置。"""
    enabled: bool = True
    page_url: str = "https://www.vidu.cn/vidu-stream/avatar"
    connect_mode: str = "playwright"


class EventSettings(BaseModel):
    """事件过滤与队列配置。"""
    gift_combo_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30)  # 连击静默暂结时间。
    comments: bool = True
    gifts: bool = True
    likes: bool = False
    enters: bool = False
    follows: bool = False
    min_interval_ms: int = 3500
    max_queue_size: int = 30
    max_message_length: int = 120
    sensitive_words: list[str] = Field(default_factory=list)


class ServerSettings(BaseModel):
    """本地 HTTP 服务配置。"""
    host: str = "127.0.0.1"
    port: int = 8795


class Settings(BaseModel):
    """聚合应用全部配置。"""
    server: ServerSettings = Field(default_factory=ServerSettings)
    douyin: DouyinSettings = Field(default_factory=DouyinSettings)
    vidu: ViduSettings = Field(default_factory=ViduSettings)
    events: EventSettings = Field(default_factory=EventSettings)


def load_settings(path: Path | None = None) -> Settings:
    """加载 YAML 文件，不存在时返回安全的默认配置。"""
    config_path = path or ROOT_DIR / "config" / "config.yaml"
    if not config_path.exists():
        return Settings()
    content: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return Settings(**content)
