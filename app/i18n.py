import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Callable
from fastapi import Request, Depends

DEFAULT_LOCALE = "zh"
SUPPORTED_LOCALES = ["zh", "en"]

class I18n:
    def __init__(self):
        self._translations: Dict[str, Dict[str, str]] = {}
        self._load_translations()

    def _load_translations(self):
        locales_dir = Path(__file__).parent / "locales"
        if not locales_dir.exists():
            locales_dir.mkdir(parents=True)
            # Create default files if they don't exist
            self._create_default_locales(locales_dir)

        for locale in SUPPORTED_LOCALES:
            file_path = locales_dir / f"{locale}.json"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    self._translations[locale] = json.load(f)
            else:
                self._translations[locale] = {}

    def _create_default_locales(self, locales_dir: Path):
        zh_content = {
            "error": {
                "plan_not_found": "交易计划 {id} 不存在",
                "signals_empty": "signal_ids不能为空",
                "signal_not_found": "未找到信号",
                "fetch_hotspots_failed": "获取市场热点失败: {error}",
                "scheduler_disabled": "调度器已禁用，无法运行异步任务",
                "job_not_found": "任务未找到: {id}",
                "auth_disabled": "身份验证已禁用",
                "login_failed": "用户名或密码错误",
                "execution_failed": "执行失败: {error}",
                "sync_failed": "同步失败: {error}",
                "cycle_failed": "周期执行失败: {error}"
            }
        }
        en_content = {
            "error": {
                "plan_not_found": "Trading plan {id} not found",
                "signals_empty": "signal_ids cannot be empty",
                "signal_not_found": "Signal not found",
                "fetch_hotspots_failed": "Failed to fetch market hotspots: {error}",
                "scheduler_disabled": "Scheduler disabled, cannot run async job",
                "job_not_found": "Job not found: {id}",
                "auth_disabled": "Authentication is disabled",
                "login_failed": "Incorrect username or password",
                "execution_failed": "Execution failed: {error}",
                "sync_failed": "Sync failed: {error}",
                "cycle_failed": "Cycle execution failed: {error}"
            }
        }
        with open(locales_dir / "zh.json", "w", encoding="utf-8") as f:
            json.dump(zh_content, f, ensure_ascii=False, indent=2)
        with open(locales_dir / "en.json", "w", encoding="utf-8") as f:
            json.dump(en_content, f, ensure_ascii=False, indent=2)

    def t(self, key: str, locale: str = DEFAULT_LOCALE, **kwargs) -> str:
        keys = key.split(".")
        val = self._translations.get(locale, {})
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, key)
            else:
                val = key
                break
        
        if isinstance(val, str):
            try:
                return val.format(**kwargs)
            except KeyError:
                return val
        return str(val)

i18n = I18n()

def get_locale(request: Request) -> str:
    accept_language = request.headers.get("accept-language", "")
    if not accept_language:
        return DEFAULT_LOCALE
    
    # Simple parser for accept-language header
    for lang in accept_language.split(","):
        code = lang.split(";")[0].strip().split("-")[0].lower()
        if code in SUPPORTED_LOCALES:
            return code
    return DEFAULT_LOCALE

def get_translator(locale: str = Depends(get_locale)):
    def translate(key: str, **kwargs):
        return i18n.t(key, locale=locale, **kwargs)
    return translate
