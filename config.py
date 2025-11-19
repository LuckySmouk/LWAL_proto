# config.py____________________________________________________________________________________________________

"""
Конфигурационный файл для AI-агента Windows
"""
import os
import logging
from pathlib import Path

# === НАСТРОЙКИ OLLAMA ===
OLLAMA_HOST = "http://localhost:11434"
MODEL = "qwen3-vl:8b"

REQUEST_TIMEOUT = 80

# Быстрые настройки генерации текста (для кратких ответов/планов)
FAST_TEXT_CONFIG = {
    "temperature": 0.5,  # Более детерминированный ответ
    "num_ctx": 4096,  # Увеличенный контекст для сложных задач
    "top_k": 20,
    "top_p": 0.7
}

# === НАСТРОЙКИ ЛОГИРОВАНИЯ ===
LOG_LEVEL = logging.DEBUG
LOG_FILE = "agent.log"
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# === ПУТИ К ФАЙЛАМ ===
BASE_DIR = Path(__file__).parent
DOCUMENTS_DIR = Path.home() / "Documents" / "AgentResults"
SCREENSHOTS_DIR = DOCUMENTS_DIR / "Screenshots"
TEMP_DIR = BASE_DIR / "temp"
CONFIG_DIR = BASE_DIR / "config"

# Создаём необходимые директории
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

BROWSER_CONFIG = {
    'use_existing': True,
    'debug_port': 9222
}



# === НАСТРОЙКИ БРАУЗЕРА ===
BROWSER_CONFIG = {
    "window_size": "1920,1080",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "page_load_timeout": 30,
    "implicit_wait": 10,
    "headless": False  # Изменить на True для фонового режима
}

# === НАСТРОЙКИ ПОИСКА ===
SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={query}",
    "yandex": "https://yandex.ru/search/?text={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/?q={query}"
}

DEFAULT_SEARCH_ENGINES = ["google", "yandex", "bing", "duckduckgo", "youtube"]
MAX_SEARCH_RESULTS = 5

# === НАСТРОЙКИ ПЛАНИРОВЩИКА ЗАДАЧ ===
TASK_CLEANUP_INTERVAL = 600  # Очистка завершённых задач через 1 час
TASK_CHECK_INTERVAL = 60  # Проверка статуса задач каждую минуту

# === НАСТРОЙКИ АНАЛИЗА ИЗОБРАЖЕНИЙ ===
IMAGE_ANALYSIS_CONFIG = {
    "temperature": 0.4,
    "num_ctx": 4096,
    "max_tokens": 2000
}


# === НАСТРОЙКИ КОНТЕКСТА ВЫПОЛНЕНИЯ ===
EXECUTION_CONFIG = {
    "max_consecutive_errors": 3,
    "progress_check_interval": 3,  # шагов
    "max_iterations_per_task": 15,
    "context_aware_execution": True,
    "adaptive_planning": True
}

# === ДИНАМИЧЕСКИЕ ПРОМПТЫ ===
DYNAMIC_PROMPT_SETTINGS = {
    "include_recent_history": 3,  # количество последних шагов в контексте
    "error_analysis_depth": "detailed",  # basic/detailed
    "progress_tracking": True
}


# === НАСТРОЙКИ УНИВЕРСАЛЬНЫХ ФУНКЦИЙ ===
UNIVERSAL_FUNCTIONS_CONFIG = {
    "mouse_move_duration": 0.5,
    "key_press_interval": 0.1,
    "default_wait_time": 2.0,
    "max_script_execution_time": 30,
    "screenshot_quality": 95
}

# === ПОДДЕРЖИВАЕМЫЕ КЛАВИШИ ===
SUPPORTED_KEYS = [
    "enter", "tab", "space", "esc", "backspace", "delete",
    "up", "down", "left", "right", "home", "end",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"
]


# === НАСТРОЙКИ СКРИНШОТОВ ===
SCREENSHOT_FORMAT = "png"
SCREENSHOT_QUALITY = 95

# === РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ ===
PATTERNS = {
    "phone": r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
    "email": r'[\w\.-]+@[\w\.-]+\.\w+',
    "url": r'https?://[^\s<>"{}|\\^`\[\]]+',
    "time_hhmm": r'([0-1]?\d|2[0-3]):([0-5]\d)',
    "time_minutes": r'(\d+)\s*(мин|минут|минуты|minutes?)',
    "time_hours": r'(\d+)\s*(час|часа|часов|hours?)'
}

# === СЕЛЕКТОРЫ ДЛЯ ВЕБ-СКРЕЙПИНГА ===
WEB_SELECTORS = {
    "google_results": ["div.g", "div[class='MjjYud']", "div[class='tF2Cxc']"],
    "youtube_results": ["yt-searchbox", "a.yt-simple-endpoint", "a.yt-simple"],
    "yandex_results": ["li[class='serp-item']", "div[class='serp-item']", "div[class='Organic']"],
    "bing_results": ["li.b_algo", "div.b_algo", "div[class='algo']"],
    "duckduckgo_results": [
        "div#links .result",
        "div#links .nrn-react-result",
        "article[data-nrn='true']"
    
    
    ],
    
    "contact_sections": {
        "contacts": "div[class*='contact'], section[class*='contact'], div[id*='contact']",
        "footer": "footer, div.footer, div[class*='footer']",
        "sidebar": "aside, div.sidebar, div[class*='sidebar']",
        "main": "main, div.main, div[class*='main']",
        "header": "header, div.header, div[class*='header']"
    },
    
    "phone_selectors": [
        'a[href^="tel:"]',
        'span[class*="phone"]',
        'div[class*="phone"]',
        'p[class*="phone"]'
    ],
    
    "email_selectors": [
        'a[href^="mailto:"]',
        'span[class*="email"]',
        'div[class*="email"]',
        'p[class*="email"]'
    ]
}

# === НАСТРОЙКИ CAPTCHA ===
CAPTCHA_SELECTORS = [
    'iframe[src*="captcha"]',
    'div[class*="captcha"]',
    'div[id*="captcha"]',
    'iframe[src*="recaptcha"]',
    'div[class*="recaptcha"]',
    'div[data-testid="captcha"]',
    'div[class*="bot-detection"]',
    'div[class*="challenge"]'
]

CAPTCHA_RETRY_DELAY = (2, 5)  # Задержка при обнаружении captcha (мин, макс)

# === КОМАНДЫ WINDOWS ===
WINDOWS_COMMANDS = {
    "camera": {
        "open": "start microsoft.windows.camera:",
        "close": "taskkill /F /IM WindowsCamera.exe"
    },
    "voice_recorder": {
        "open": "start ms-soundrecorder:",
        "close": "taskkill /F /IM SoundRecorder.exe"
    },
    "screenshot": "snippingtool /clip",
    "task_manager": "taskmgr",
    "control_panel": "control",
    "system_info": "msinfo32"
}

# === ПОДДЕРЖИВАЕМЫЕ ФОРМАТЫ ФАЙЛОВ ===
SUPPORTED_FILE_FORMATS = {
    "images": [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"],
    "documents": [".txt", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv"],
    "audio": [".mp3", ".wav", ".m4a", ".ogg"],
    "video": [".mp4", ".avi", ".mkv", ".mov"]
}

# === НАСТРОЙКИ БЕЗОПАСНОСТИ ===
SECURITY_CONFIG = {
    "max_file_size_mb": 500,  # Максимальный размер файла для обработки
    "allowed_extensions": [
        ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".csv", ".json", ".xml"
    ],
    "blocked_commands": [
        "format", "del /f /s /q", "rd /s /q", "shutdown", "restart"
    ],
    "safe_mode": True  # Требовать подтверждение для критичных операций
}

# === ОГРАНИЧЕНИЯ ===
LIMITS = {
    "max_retries": 3,
    "max_concurrent_tasks": 5,
    "max_links_to_process": 50,
    "max_screenshot_size_mb": 10,
    "max_text_length": 10000
}

def get_windows_documents_path():
    """Получает путь к папке Documents в Windows"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        )
        documents_path, _ = winreg.QueryValueEx(key, "Personal")
        winreg.CloseKey(key)
        return Path(documents_path)
    except Exception:
        return Path.home() / "Documents"

def setup_logging():
    """Настраивает систему логирования"""
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

# Инициализация логгера
logger = setup_logging()