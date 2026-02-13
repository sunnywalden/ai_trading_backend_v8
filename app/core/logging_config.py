import logging
import sys
from typing import Dict, Any

def setup_logging(level=logging.INFO):
    """
    配置全局日志格式
    格式: 2024-03-21 10:00:00.123 | INFO    | module:function:line - message
    """
    
    # 定义基础格式
    # %(levelname)-7s 让级别对齐 (INFO, WARNING, ERROR)
    # %(name)s:%(funcName)s:%(lineno)d 提供代码位置
    log_format = "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 配置根日志
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    
    # 清除现有的 handlers 避免重复打印
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # 抑制一些过于啰嗦的库日志
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    # 确保 uvicorn 使用我们的格式
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging_logger = logging.getLogger(logger_name)
        if logging_logger.handlers:
            logging_logger.handlers[0].setFormatter(formatter)
        else:
            logging_logger.addHandler(handler)

    logging.info("🚀 Logging system initialized with standardized format")
    return root_logger
