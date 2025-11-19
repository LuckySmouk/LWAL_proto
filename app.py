# app.py____________________________________________________________________________________________________

"""

"""
import json
import re
import threading
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from pathlib import Path
try:
    import pyautogui  # для определения разрешения экрана
except Exception:
    pyautogui = None

# Импорты модулей
import config
from run_check_model import check_ollama, call_ollama, analyze_image
from tools_registry import TOOLS

# Импорты менеджеров
from browser_function import BrowserManager
from win_command_func import WindowsCommandManager
from win_filesystem_func import FileSystemManager
from win_filesystem_func import write_csv_file
from browser_function import initialize_browser

# Импорты отдельных функций, которые не являются частью менеджеров
from function_factory import create_python_script, execute_python_script

logger = config.logger


COORDINATE_PROMPT_MARKER = "[[COORDINATE_RESPONSE_JSON]]"


class AIAgent:
    """
    Главный класс AI-агента для Windows.
    
    Отвечает за:
    - Анализ пользовательских запросов и разбиение на задачи
    - Создание планов выполнения через LLM
    - Итеративное выполнение планов
    - Обработку ошибок и автоматическое переключение на fallback'и
    - Нормализацию результатов инструментов
    
    Пример использования:
        agent = AIAgent()
        result = agent.run_task("Открой телеграм и отправь сообщение", auto_execute=True)
    """

    def __init__(self) -> None:
        self.tools = self._load_tools()
        self.instructions = self._load_instructions()
        self.prompts = self._load_prompts()
        self.task_history: List[Dict[str, Any]] = []
        self.failed_attempts: Dict[str, int] = {}  # Счетчик неудач по задачам
        self._url_iters: Dict[str, int] = {}
        self._frozen_tools: set = set()

        # Инициализация менеджеров
        self.browser_manager = BrowserManager()
        self.command_manager = WindowsCommandManager()
        self.fs_manager = FileSystemManager()

        # Загружаем историю, если есть
        try:
            hist_path = Path(config.DOCUMENTS_DIR) / "task_history.json"
            if hist_path.exists():
                loaded = self.fs_manager.read_file(str(hist_path))
                # read_file в проекте возвращает dict: {"status":..., "content":...} или прямой контент
                if isinstance(loaded, dict):
                    content = loaded.get("content")
                    if isinstance(content, str):
                        try:
                            self.task_history = json.loads(content)
                        except Exception:
                            # если content не json — попытка прочитать как py literal
                            self.task_history = []
                    elif isinstance(content, list):
                        self.task_history = content
                    else:
                        # иногда read_file может возвращать {'status':'success', 'content': [{'...'}]}
                        if loaded.get("status") == "success" and isinstance(loaded.get("content"), list):
                            content = loaded.get("content")
                            if isinstance(content, list):
                                self.task_history = content
                            else:
                                self.task_history = []  # безопасное приведение
                        else:
                            self.task_history = []
                elif isinstance(loaded, str):
                    try:
                        self.task_history = json.loads(loaded)
                    except Exception:
                        self.task_history = []
        except Exception as e:
            logger.warning(f"⚠️ Не удалось загрузить историю задач: {e}")
            self.task_history = []

        # Кэш допустимых аргументов для инструментов (имя → множество ключей)
        try:
            self._allowed_arg_keys: Dict[str, set] = {}
            # базовые ключи из реестра инструментов
            for t in (self.tools or []):
                name = t.get("name")
                params = set((t.get("parameters") or {}).keys())
                if name:
                    self._allowed_arg_keys[name] = params
            # дополнения для нормализованных ключей, используемых внутри кода
            extras = {
                # Браузер
                "initialize_browser": {"headless", "use_existing", "cdp_url", "debug_port"},
                "navigate_to_url": {"url", "wait_for_element", "timeout"},
                "take_screenshot": {"filename", "directory"},
                "extract_text_from_page": {"selectors", "text_patterns"},
                "find_contact_info": {"contact_types"},
                "click_element": {"selector", "by", "timeout"},
                "fill_form": {"form_fields", "submit_selector"},
                "scroll_page": {"direction", "amount"},
                "get_page_source": {"trim_length"},
                "execute_javascript": {"script"},
                # ФС
                "read_file": {"filepath", "path"},
                "write_file": {"filepath", "path", "content", "overwrite"},
                "write_csv_file": {"filepath", "path", "data", "headers", "overwrite"},
                "delete_file": {"filepath", "path"},
                "list_directory": {"dirpath", "path"},
                "copy_file": {"source", "destination", "src", "dst"},
                "move_file": {"source", "destination", "src", "dst"},
                "create_directory": {"dirpath", "path"},
                "get_file_info": {"filepath", "path"},
                # Система
                "execute_system_command": {"command", "working_dir"},
                "open_application": {"app_name", "args"},
                "open_application_advanced": {"app_name", "args"},
                "find_executable": {"app_name"},
                "close_application": {"app_name", "force"},
                "list_processes": {"name_filter"},
                # Камера/аудио
                "take_photo": {"output_path", "filename", "directory"},
                # Разное
                "create_python_script": {"code", "filename", "directory"},
                "execute_python_script": {"script_path", "timeout"},
                "wait_for_seconds": {"seconds"},
                "analyze_image": {"image_path", "path", "question"},
                "analyze_screen_region": {"x", "y", "width", "height", "question"},
                "take_desktop_screenshot": {"filename", "directory"},
                "click_at_coordinates": {"x", "y", "button", "clicks"},
                "press_key": {"key", "presses"},
                "press_hotkey": {"keys"},
                "type_text": {"text", "interval"},
                "schedule_task": {"action", "delay_minutes", "delay_hours", "specific_time", "command", "filename", "custom_action"},
                "schedule_recurring_task": {"action", "every_minutes", "duration_hours", "command", "filename", "custom_action"},
                "cancel_scheduled_task": {"task_id", "task_name"},
            }
            for k, v in extras.items():
                self._allowed_arg_keys[k] = (self._allowed_arg_keys.get(k) or set()) | set(v)
        except Exception:
            self._allowed_arg_keys = {}

        # Конфигурация GUI-верификации (политика и радиус)
        try:
            gui_cfg = (self.instructions or {}).get("gui", {}) if isinstance(self.instructions, dict) else {}
            self.gui_verify_policy: str = str(gui_cfg.get("verify_policy", "always")).lower()  # always|on_failure|never
            self.gui_verify_radius: int = int(gui_cfg.get("verify_radius", 80))
            self.gui_verify_max_attempts: int = max(1, int(gui_cfg.get("verify_max_attempts", 3)))
            # политика повторного клика при отрицательной верификации
            self.gui_refocus_retry: bool = bool(gui_cfg.get("refocus_retry", True))
            self.gui_refocus_offsets: List[Tuple[int, int]] = gui_cfg.get("refocus_offsets", [
                [0, 0], [8, 0], [-8, 0], [0, 8], [0, -8]
            ])
            # нормализуем формат на list[tuple]
            self.gui_refocus_offsets = [(int(x), int(y)) for x, y in self.gui_refocus_offsets if isinstance(x, (int, float)) and isinstance(y, (int, float))]
        except Exception:
            self.gui_verify_policy = "always"
            self.gui_verify_radius = 80
            self.gui_verify_max_attempts = 3
            self.gui_refocus_retry = True
            self.gui_refocus_offsets = [(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]


    def _count_failed_attempts(self, step_description: str, tool_name: str) -> int:
        """Считает количество неудачных попыток для шага"""
        key = f"{step_description}_{tool_name}"
        return self.failed_attempts.get(key, 0)

    def _increment_failed_attempts(self, step_description: str, tool_name: str):
        """Увеличивает счетчик неудачных попыток"""
        key = f"{step_description}_{tool_name}"
        self.failed_attempts[key] = self.failed_attempts.get(key, 0) + 1

    def _reset_failed_attempts(self, step_description: str, tool_name: str):
        """Сбрасывает счетчик неудачных попыток"""
        key = f"{step_description}_{tool_name}"
        self.failed_attempts[key] = 0

    def _find_last_successful_step(self, executed_steps: List[Dict[str, Any]], tool_name: str) -> Optional[Dict[str, Any]]:
        """Находит последний успешный шаг с указанным инструментом."""
        normalized = (tool_name or "").lower().strip()
        if not normalized:
            return None
        for step in reversed(executed_steps or []):
            name = (step.get("tool") or step.get("name") or "").lower().strip()
            if name == normalized and step.get("status") == "success":
                return step
        return None

    def _infer_action_from_description(self, description: str) -> str:
        desc = (description or "").lower()
        if any(k in desc for k in ("введ", "input", "type", "напеч")):
            return "type"
        if any(k in desc for k in ("провер", "verify", "подтвер", "фокус")):
            return "verify"
        if any(k in desc for k in ("поиск", "найд", "locate", "анализ")):
            return "locate"
        return "click"

    def _format_coordinate_question(self, question: str, action_hint: str = "click") -> str:
        base = (question or "").strip()
        if COORDINATE_PROMPT_MARKER in base:
            return base
        action = action_hint or "locate"
        template = (
            "\n\n[[COORDINATE_RESPONSE_JSON]]\n"
            "Ответь ТОЛЬКО JSON в одной строке: "
            "{\"status\":\"success|fail\",\"action\":\"%s\",\"coordinates\":[{\"x\":123,\"y\":456,\"label\":\"element\",\"confidence\":0.95}],\"reason\":\"кратко\"}. "
            "Если элемент не найден, верни status=\"fail\" и пустой массив coordinates." % action
        )
        return f"{base}{template}" if base else template

    def _extract_coordinate_analysis(self, analysis: Any) -> Tuple[bool, List[Dict[str, Any]], str]:
        payload = analysis
        if isinstance(analysis, dict):
            payload = analysis.get("analysis") or analysis.get("stdout") or analysis
        text_repr = str(payload or "").strip()
        coords: List[Dict[str, Any]] = []
        ok = False
        try:
            parsed = json.loads(text_repr) if isinstance(text_repr, str) else payload
        except Exception:
            parsed = payload if isinstance(payload, dict) else None
        if isinstance(parsed, dict):
            coords_val = parsed.get("coordinates")
            if isinstance(coords_val, list):
                coords = [c for c in coords_val if isinstance(c, dict)]
            status = str(parsed.get("status", "")).lower()
            ok = status == "success" or bool(coords)
            return ok, coords, text_repr
        lower_text = text_repr.lower()
        if "yes" in lower_text and "no" not in lower_text:
            ok = True
        return ok, coords, text_repr

    def _detect_task_completion(self, original_task: Optional[str], executed_steps: List[Dict[str, Any]]) -> bool:
        """Грубая эвристика для определения, что основная задача выполнена (без повторного GUI-цикла)."""
        if not original_task or not executed_steps:
            return False
        task_lower = original_task.lower()

        def _has(tool_name: str, text_markers: Optional[List[str]] = None) -> bool:
            markers = [m.lower() for m in (text_markers or [])]
            for step in executed_steps:
                if step.get("status") != "success":
                    continue
                tool = (step.get("tool") or step.get("name") or "").lower()
                if tool != tool_name.lower():
                    continue
                if not markers:
                    return True
                desc = (step.get("description") or "").lower()
                if any(marker in desc for marker in markers):
                    return True
            return False

        message_task = any(word in task_lower for word in ("напиши", "отправ", "message", "сообщение", "write", "send"))
        search_task = any(word in task_lower for word in ("найди", "найти", "поиск", "search", "find"))

        has_message_type = _has("type_text", ["ввод", "сообщен", "message", "текст"])
        has_message_send = _has("press_key", ["enter", "отправ", "send"])
        has_final_screenshot = _has("take_desktop_screenshot", ["финаль", "final", "message_sent", "подтверждение"])

        if message_task and has_message_type and has_message_send and has_final_screenshot:
            return True

        if search_task:
            found_contact_click = _has("click_at_coordinates", ["контакт", "contact", "результат", "result"])
            search_snapshot = _has("take_desktop_screenshot", ["результат", "search", "поиск"])
            if found_contact_click and search_snapshot and (not message_task or has_final_screenshot):
                return True

        return False

    def _prepare_gui_analysis_step(self, original_task: str, executed_steps: List[Dict[str, Any]], description: str) -> Dict[str, Any]:
        """Возвращает следующий шаг для GUI-анализа: анализ существующего скриншота или создание нового."""
        base_step = len(executed_steps) + 1
        last_screenshot = self._find_last_successful_step(executed_steps, "take_desktop_screenshot")
        screenshot_path = None
        if last_screenshot:
            result_payload = last_screenshot.get("result") or {}
            screenshot_path = result_payload.get("file_path") or result_payload.get("filepath") or result_payload.get("path")
            if not screenshot_path:
                filename = (last_screenshot.get("args") or {}).get("filename")
                if filename:
                    screenshots_dir = getattr(config, "SCREENSHOTS_DIR", None)
                    if not screenshots_dir:
                        screenshots_dir = Path(config.DOCUMENTS_DIR) / "Screenshots"
                    screenshot_path = str(Path(screenshots_dir) / filename)
        if screenshot_path:
            question = (
                f"Проанализируй интерфейс и найди координаты элементов для задачи: {original_task}. "
                "Верни JSON вида {\"coordinates\":[{\"x\":X,\"y\":Y,\"label\":\"target\",\"confidence\":0-1}]} и кратко опиши найденные области."
            )
            return {
                "step": base_step,
                "description": description or "Анализ текущего скриншота интерфейса",
                "tool": "analyze_image",
                "args": {
                    "image_path": screenshot_path,
                    "question": self._format_coordinate_question(question, "locate")
                }
            }
        filename = f"app_interface_{int(time.time())}.png"
        return {
            "step": base_step,
            "description": description or "Сделать скриншот интерфейса приложения",
            "tool": "take_desktop_screenshot",
            "args": {"filename": filename}
        }




    def _load_tools(self) -> List[Dict[str, Any]]:
        """Загружает полный список инструментов агента"""
        return TOOLS

    def _load_instructions(self) -> Dict:
        """Загружает инструкции из файла"""
        try:
            instruct_path = config.CONFIG_DIR / "instruct.json"
            if instruct_path.exists():
                with open(instruct_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            # fallback: искать в корне проекта
            root_path = Path(__file__).parent / "instruct.json"
            if root_path.exists():
                with open(root_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось загрузить instruct.json: {e}")

        return {}

    def _load_prompts(self) -> Dict:
        """Загружает промпты из файла"""
        try:
            prompt_path = config.CONFIG_DIR / "prompt.json"
            if prompt_path.exists():
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            # fallback: искать в корне проекта
            root_path = Path(__file__).parent / "prompt.json"
            if root_path.exists():
                with open(root_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось загрузить prompt.json: {e}")

        return {}


    def _handle_repeated_failure(self, original_task: str, failed_step: Dict, executed_steps: List[Dict]) -> Optional[Dict]:
        """Обрабатывает повторяющиеся неудачи и создает динамическое решение"""
        step_description = failed_step.get("description", "")
        tool_name = failed_step.get("tool") or failed_step.get("name", "")
        
        failed_count = self._count_failed_attempts(step_description, tool_name)
        
        if failed_count >= 3:
            logger.warning(f"🚨 Превышено количество неудачных попыток ({failed_count}) для шага: {step_description}")

            def _sequence_response(sequence: List[Dict]) -> Dict:
                if not sequence:
                    return {}
                return {
                    "step": sequence[0].get("step", failed_step.get("step", 1)),
                    "description": "dynamic_sequence",
                    "tool": "dynamic_sequence",
                    "args": {"sequence": sequence},
                    "dynamic_solution": True
                }

            def _build_gui_sequence() -> Optional[Dict]:
                base_step = failed_step.get("step", 1)
                screenshot_name = f"gui_fallback_{int(time.time())}.png"
                screenshot_path = str(Path(config.SCREENSHOTS_DIR) / screenshot_name)
                question = (
                    "Определи абсолютные координаты X,Y для действия: "
                    f"{step_description or original_task}. Верни JSON вида {{\"coordinates\":[{{\"x\":X,\"y\":Y}}]}}"
                )
                seq = [
                    {
                        "step": base_step,
                        "description": "Сделать свежий скриншот рабочего стола",
                        "tool": "take_desktop_screenshot",
                        "args": {"filename": screenshot_name}
                    },
                    {
                        "step": base_step + 0.1,
                        "description": "Проанализировать скриншот и получить координаты",
                        "tool": "analyze_image",
                        "args": {"image_path": screenshot_path, "question": question}
                    },
                    {
                        "step": base_step + 0.2,
                        "description": "Клик по найденным координатам",
                        "tool": "click_at_coordinates",
                        "args": {"x": 0, "y": 0, "button": "left", "clicks": 1}
                    },
                    {
                        "step": base_step + 0.3,
                        "description": "Скриншот для проверки результата",
                        "tool": "take_desktop_screenshot",
                        "args": {"filename": f"verify_{screenshot_name}"}
                    }
                ]
                return _sequence_response(seq)

            def _build_file_sequence(file_path: Optional[str]) -> Optional[Dict]:
                if not file_path:
                    return None
                base_step = failed_step.get("step", 1)
                temp_dir = Path(config.TEMP_DIR)
                temp_dir.mkdir(parents=True, exist_ok=True)
                script_filename = f"file_parser_{int(time.time())}.py"
                script_path = str(temp_dir / script_filename)
                output_path = str(temp_dir / f"parsed_{Path(file_path).stem}_{int(time.time())}.txt")
                script_code = f"""
import re
from pathlib import Path
source = Path(r"{file_path}")
text = source.read_text(encoding='utf-8', errors='ignore')
links = re.findall(r"https?://\\S+", text)
output = Path(r"{output_path}")
output.write_text('\n'.join(links), encoding='utf-8')
print(f"Extracted {{len(links)}} links from {file_path} -> {output_path}")
"""
                seq = [
                    {
                        "step": base_step,
                        "description": f"Повторно прочитать файл {file_path} для диагностики",
                        "tool": "read_file",
                        "args": {"filepath": file_path}
                    },
                    {
                        "step": base_step + 0.1,
                        "description": "Создать Python-скрипт для парсинга файла",
                        "tool": "create_python_script",
                        "args": {
                            "filename": script_filename,
                            "directory": str(temp_dir),
                            "code": script_code
                        }
                    },
                    {
                        "step": base_step + 0.2,
                        "description": "Выполнить сгенерированный скрипт",
                        "tool": "execute_python_script",
                        "args": {"script_path": script_path, "timeout": 120}
                    },
                    {
                        "step": base_step + 0.3,
                        "description": "Проверить результаты парсинга",
                        "tool": "read_file",
                        "args": {"filepath": output_path}
                    }
                ]
                return _sequence_response(seq)

            def _build_browser_sequence(url: Optional[str], form_args: Optional[Dict]) -> Optional[Dict]:
                base_step = failed_step.get("step", 1)
                seq: List[Dict] = [
                    {
                        "step": base_step,
                        "description": "Инициализация браузера в видимом режиме",
                        "tool": "initialize_browser",
                        "args": {"use_existing": True, "headless": False}
                    }
                ]
                if url:
                    seq.append({
                        "step": base_step + 0.1,
                        "description": f"Переход на {url}",
                        "tool": "navigate_to_url",
                        "args": {"url": url, "timeout": 30}
                    })
                if form_args:
                    seq.append({
                        "step": base_step + 0.2,
                        "description": "Повторное заполнение формы",
                        "tool": "fill_form",
                        "args": form_args
                    })
                seq.extend([
                    {
                        "step": base_step + 0.3,
                        "description": "Небольшая пауза для загрузки",
                        "tool": "wait_for_seconds",
                        "args": {"seconds": 2}
                    },
                    {
                        "step": base_step + 0.4,
                        "description": "Скриншот для проверки веб-интерфейса",
                        "tool": "take_desktop_screenshot",
                        "args": {"filename": f"web_verify_{int(time.time())}.png"}
                    }
                ])
                return _sequence_response(seq)

            # Специальный, предсказуемый fallback для проблем с запуском приложений
            # Если ошибка связана с открытием приложения или выполнением команды запуска,
            # формируем план: 1) попробовать найти путь к exe через find_executable, 2) запустить через open_application_advanced
            low_tool = (tool_name or "").lower()
            if any(k in low_tool for k in ("open", "telegram", "application", "start", "exe", "launch")):
                app_arg = None
                # Пытаемся извлечь имя приложения из аргументов
                try:
                    args = failed_step.get("result") or {}
                    # если в failed_step есть args
                    if isinstance(failed_step.get("args"), dict):
                        app_arg = failed_step.get("args", {}).get("app_name") or failed_step.get("args", {}).get("application") or failed_step.get("args", {}).get("app")
                    # иначе, попробуем из description
                    if not app_arg:
                        import re
                        m = re.search(r'"([^"]+)"', step_description)
                        if m:
                            app_arg = m.group(1)
                except Exception:
                    app_arg = None

                if app_arg:
                    logger.info(f"🔧 Динамический fallback: попытаемся найти exe и запустить '{app_arg}'")
                    # Шаг 1: find_executable
                    step_find = {
                        "step": failed_step.get("step", 1),
                        "description": f"Найти путь к исполняемому файлу для {app_arg}",
                        "tool": "find_executable",
                        "args": {"app_name": app_arg}
                    }
                    # Шаг 2: запуск найденного пути
                    step_run = {
                        "step": failed_step.get("step", 1) + 1,
                        "description": f"Запустить {app_arg} по найденному пути",
                        "tool": "open_application_advanced",
                        "args": {"app_name": app_arg}
                    }
                    # Возвращаем динамический шаг — модель/планировщик выполнит find_executable, затем open_application_advanced
                    return {"step": step_find["step"], "description": "dynamic_sequence", "tool": "dynamic_sequence", "args": {"sequence": [step_find, step_run]}, "dynamic_solution": True}

            gui_tools = {"click_at_coordinates", "click_element", "press_key", "press_hotkey", "type_text", "analyze_screen_region", "analyze_image"}
            file_tools = {"read_file", "write_file", "write_csv_file", "file_processing", "file_read"}
            browser_tools = {"initialize_browser", "navigate_to_url", "fill_form", "click_element", "execute_javascript"}

            if any(k in low_tool for k in gui_tools):
                gui_sequence = _build_gui_sequence()
                if gui_sequence:
                    logger.info("🧩 Применяем GUI fallback-последовательность")
                    return gui_sequence

            file_path = (failed_step.get("args") or {}).get("filepath") or (failed_step.get("args") or {}).get("path")
            if any(k in low_tool for k in file_tools) and file_path:
                file_sequence = _build_file_sequence(file_path)
                if file_sequence:
                    logger.info("📁 Применяем файловый fallback (скрипт)")
                    return file_sequence

            url_arg = (failed_step.get("args") or {}).get("url")
            form_args = failed_step.get("args") if tool_name == "fill_form" else None
            if any(k in low_tool for k in browser_tools):
                browser_sequence = _build_browser_sequence(url_arg, form_args)
                if browser_sequence:
                    logger.info("🌐 Применяем браузерный fallback-поток")
                    return browser_sequence

            # Общий путь: попытаемся сгенерировать динамическое решение через LLM
            dynamic_solution = self._create_dynamic_solution(original_task, failed_step, executed_steps)
            return dynamic_solution

        return None

    def _create_dynamic_solution(self, original_task: str, failed_step: Dict, executed_steps: List[Dict]) -> Optional[Dict]:
        """Создает динамическое решение после многократных неудач"""
        
        # Формируем контекст неудач
        failure_context = []
        for step in executed_steps[-5:]:
            if step.get("status") == "failed":
                failure_context.append(f"- {step.get('description')}: {step.get('result', {}).get('error', 'неизвестная ошибка')}")
        
        context_str = "\n".join(failure_context)
        
        import dynamic_prompts as _dp
        # Формируем запрет повторно используемого инструмента и дополнительные указания
        forbidden = []
        tn = (failed_step.get("tool") or failed_step.get("name") or "").strip()
        if tn:
            forbidden.append(tn)
        guidance_parts = []
        # Браузерные подсказки
        if tn == "navigate_to_url":
            guidance_parts.append("Проверь адресную строку: возьми скриншот и проанализируй видимый URL (take_screenshot + analyze_image).")
            guidance_parts.append("Если в аргументах указан шаблон 'Ссылка из файла' или 'Следующая ссылка из файла', сначала прочитай файл через read_file и явно передай корректный URL.")
            guidance_parts.append("Попробуй использовать initialize_browser(use_existing: true) и переключиться на уже открытый браузер, затем ввести URL через ctrl+l, type_text, press_key.")
        dynamic_prompt = _dp.build_dynamic_solution_prompt(original_task, failed_step, executed_steps, forbidden_tools=forbidden, guidance="\n".join(guidance_parts))
        
        try:
            response = call_ollama(dynamic_prompt, fast=False, options={"temperature": 0.2, "num_predict": 1024}, format="json")
            solution = self._extract_json_from_text(response)
            
            if isinstance(solution, dict):
                logger.info(f"🎯 Получено динамическое решение типа: {solution.get('solution_type')}")
                
                # Исполняем решение в зависимости от типа
                if solution.get('solution_type') == 'new_function':
                    new_func_spec = solution.get('implementation', {}).get('new_function_spec', {})
                    if new_func_spec:
                        creation_result = self._create_function_from_screenshot(new_func_spec, dynamic_prompt)
                        if creation_result and creation_result.get('status') == 'success':
                            # Возвращаем шаг для вызова новой функции
                            return {
                                "step": failed_step.get("step", 1),
                                "description": f"Выполнение созданной функции: {new_func_spec.get('name')}",
                                "tool": "execute_python_script",
                                "args": {
                                    "script_path": creation_result.get('script_path'),
                                    "function_name": new_func_spec.get('name')
                                },
                                "dynamic_solution": True
                            }
                
                elif solution.get('solution_type') == 'system_command':
                    # Используем системные команды
                    return {
                        "step": failed_step.get("step", 1),
                        "description": f"Решение через системные команды: {solution.get('description', '')}",
                        "tool": "execute_system_command",
                        "args": {
                            "command": solution.get('implementation', {}).get('details', 'echo "Решение через команды"')
                        },
                        "dynamic_solution": True
                    }
                
                elif solution.get('solution_type') == 'python_script':
                    # Создаем Python скрипт
                    script_code = solution.get('implementation', {}).get('details', 'print("Динамическое решение")')
                    script_result = self.execute_tool({
                        "name": "create_python_script",
                        "arguments": {
                            "filename": f"dynamic_solution_{int(time.time())}.py",
                            "code": script_code
                        }
                    })
                    
                    if script_result and script_result.get("status") == "success":
                        return {
                            "step": failed_step.get("step", 1),
                            "description": f"Выполнение динамического Python скрипта",
                            "tool": "execute_python_script",
                            "args": {
                                "script_path": script_result.get("file_path")
                            },
                            "dynamic_solution": True
                        }
                
                elif solution.get('solution_type') == 'coordinates':
                    # Используем координаты напрямую
                    return {
                        "step": failed_step.get("step", 1),
                        "description": f"Решение через координаты: {solution.get('description', '')}",
                        "tool": "click_at_coordinates",
                        "args": {
                            "x": 500,  # Дефолтные координаты, должны быть из анализа
                            "y": 300
                        },
                        "dynamic_solution": True
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания динамического решения: {e}")
            return None

    def _create_function_from_screenshot(self, function_spec: Dict, context: str) -> Dict:
        """Создает новую функцию через анализ скриншота и генерацию кода"""
        try:
            logger.info(f"🔄 Создание функции через анализ скриншота: {function_spec.get('name')}")
            
            # Делаем скриншот для анализа
            screenshot_result = self.execute_tool({
                "name": "take_desktop_screenshot", 
                "arguments": {"filename": f"debug_{function_spec.get('name', 'func')}.png"}
            })
            
            if screenshot_result.get("status") != "success":
                return {"error": "Не удалось сделать скриншот для анализа"}
            
            screenshot_path = screenshot_result.get("file_path")
            
            # Анализируем скриншот для понимания интерфейса
            analysis_prompt = f"""
            Задача: {function_spec.get('description', '')}
            Контекст: {context}
            
            Проанализируй интерфейс на скриншоте и предложи:
            1. Координаты для кликов
            2. Текст для ввода  
            3. Последовательность действий
            4. CSS селекторы если видны элементы
            
            Верни JSON в формате:
            {{
                "analysis": "анализ интерфейса",
                "coordinates": [{{"x": 100, "y": 200, "action": "click", "description": "описание"}}],
                "text_inputs": [{{"text": "текст", "description": "для чего"}}],
                "sequence": ["действие1", "действие2"],
                "recommended_tools": ["tool1", "tool2"]
            }}
            """
            
            # Формируем вопрос для анализа интерфейса через модуль динамических промптов
            from dynamic_prompts import build_ui_analysis_prompt
            analysis_prompt = build_ui_analysis_prompt(function_spec, context)

            analysis_result = self.execute_tool({
                "name": "analyze_image",
                "arguments": {
                    "image_path": screenshot_path,
                    "question": analysis_prompt
                }
            })
            
            # Создаем Python скрипт на основе анализа
            script_code = self._generate_script_from_analysis(function_spec, analysis_result)
            
            # Сохраняем и выполняем скрипт
            script_result = self.execute_tool({
                "name": "create_python_script",
                "arguments": {
                    "filename": f"dynamic_{function_spec.get('name')}.py",
                    "code": script_code
                }
            })
            
            return {
                "status": "success",
                "function_created": function_spec.get('name'),
                "script_path": script_result.get("file_path"),
                "analysis": analysis_result
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания функции из скриншота: {e}")
            return {"error": f"Ошибка создания функции: {str(e)}"}

    def _generate_script_from_analysis(self, function_spec: Dict, analysis: Any) -> str:
        """Генерирует код Python скрипта на основе анализа"""
        function_name = function_spec.get('name', 'dynamic_function')
        description = function_spec.get('description', '')
        
        # Парсим анализ для извлечения координат и действий
        coordinates = []
        text_inputs = []
        
        if isinstance(analysis, dict):
            if 'analysis' in analysis:
                analysis_str = str(analysis['analysis'])
            else:
                analysis_str = str(analysis)
            
            # Извлекаем координаты из анализа (упрощенный парсинг)
            if isinstance(analysis, dict) and 'coordinates' in analysis:
                coordinates = analysis['coordinates']
            if isinstance(analysis, dict) and 'text_inputs' in analysis:
                text_inputs = analysis['text_inputs']
        else:
            analysis_str = str(analysis)
        
        # Генерируем код скрипта
        script = f'''
    \"\"\"
    Динамически созданная функция: {function_name}
    Описание: {description}
    Сгенерировано на основе анализа: {analysis_str[:200]}...
    \"\"\"

    import time
    import pyautogui
    import subprocess
    import os

    def {function_name}():
        \"\"\"Выполняет задачу: {description}\"\"\"
        try:
            # Автоматически сгенерированные действия
            print("Выполнение динамической функции: {function_name}")
            '''
        
        # Добавляем действия по координатам
        for i, coord in enumerate(coordinates[:5]):  # Ограничиваем 5 действиями
            if isinstance(coord, dict) and 'x' in coord and 'y' in coord:
                action = coord.get('action', 'click')
                if action == 'click':
                    script += f'''
            # {coord.get('description', f'Действие {i+1}')}
            pyautogui.click({coord['x']}, {coord['y']})
            time.sleep(1)
                    '''
        
        # Добавляем ввод текста
        for i, text_input in enumerate(text_inputs[:3]):
            if isinstance(text_input, dict) and 'text' in text_input:
                script += f'''
            # {text_input.get('description', f'Ввод текста {i+1}')}
            pyautogui.write("{text_input['text']}")
            time.sleep(0.5)
                '''
        
        script += f'''
            print("Функция {function_name} выполнена успешно")
            return {{"status": "success", "message": "Динамическая функция выполнена"}}
        except Exception as e:
            return {{"error": str(e)}}
        
    if __name__ == "__main__":
        {function_name}()
        '''
        
        return script


    def _normalize_tool_result(self, result: Any) -> Dict[str, Any]:
        """Нормализует форму возвращаемого значения от инструментов.
        Гарантирует словарь с ключами: status, error, stdout, stderr, file_path (если есть).
        Не удаляет дополнительные поля, а лишь дополняет/нормализует их.
        """
        try:
            if result is None:
                return {"status": "error", "error": "no result", "stdout": "", "stderr": ""}

            # Если уже dict — расширяем/нормализуем
            if isinstance(result, dict):
                res = dict(result)  # shallow copy
                # Normalize status
                st = res.get("status")
                if st is None:
                    # Если есть error — помечаем как error, иначе success
                    st = "error" if res.get("error") else "success"
                res["status"] = str(st)

                # Ensure error field exists (None if no error)
                if "error" not in res:
                    res["error"] = None

                # Normalize file path keys
                if "file_path" not in res:
                    for k in ("filepath", "path", "file"):
                        if k in res and isinstance(res.get(k), str):
                            res["file_path"] = res.get(k)
                            break

                # Ensure stdout/stderr are strings
                res["stdout"] = "" if res.get("stdout") is None else str(res.get("stdout"))
                res["stderr"] = "" if res.get("stderr") is None else str(res.get("stderr"))

                return res

            # For primitives or other types — wrap into success with stdout
            return {"status": "success", "error": None, "stdout": str(result), "stderr": "", "result": result}
        except Exception:
            # In case of any unexpected error while normalizing
            try:
                return {"status": "error", "error": "normalization_failed", "stdout": "", "stderr": ""}
            except Exception:
                return {"status": "error", "error": "normalization_failed"}

    def _log_unhandled_keys(self, tool_name: str, result: Dict[str, Any]) -> None:
        """Логирует необработанные или неожиданные ключи в результатах инструментов"""
        try:
            standard_keys = {"status", "error", "stdout", "stderr", "file_path"}
            expected_keys_by_tool = {
                "execute_system_command": {"returncode", "command", "execution_time"},
                "take_desktop_screenshot": {"file_path", "size", "resolution"},
                "click_at_coordinates": {"coordinates", "button", "clicks"},
                "locate_app_icon_on_desktop": {"image", "x", "y", "coordinates"},
                "list_processes": {"count", "processes"},
                "get_system_info": {"os", "cpu_count", "memory", "disk"},
                "read_file": {"filepath", "filename", "extension", "size", "encoding", "content", "type", "structure"},
                "write_file": {"filepath", "size"},
                "find_executable": {"path"},
                "open_application_advanced": {"application", "path"},
                "open_application": {"application", "message"},
                "search_web": {"results", "query"},
                "navigate_to_url": {"url", "title"},
                "fill_form": {"fields_filled", "submitted"},
                "take_screenshot": {"file_path", "resolution"},
                "analyze_screen_region": {"status", "analysis", "question", "region"},
            }
            expected_keys = standard_keys.copy()
            expected_keys.update(expected_keys_by_tool.get(tool_name, set()))
            actual_keys = set(result.keys()) if isinstance(result, dict) else set()
            unhandled_keys = actual_keys - expected_keys
            if unhandled_keys:
                logger.debug(f"🔍 Инструмент '{tool_name}' вернул неожиданные ключи: {unhandled_keys}")
                if len(unhandled_keys) >= 3:
                    logger.info(f"⚠️ '{tool_name}' вернул {len(unhandled_keys)} неожиданных ключей — требуется обновление схемы")
        except Exception as e:
            logger.debug(f"🔧 Ошибка логирования ключей: {e}")

    def _sanitize_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Удаляет из аргументов неизвестные ключи, чтобы избежать TypeError у функций-инструментов."""
        try:
            if not isinstance(args, dict):
                return args
            allowed = self._allowed_arg_keys.get(tool_name)
            if not allowed:
                return args
            cleaned = {k: v for k, v in args.items() if k in allowed}
            dropped = set(args.keys()) - set(cleaned.keys())
            if dropped:
                logger.debug(f"🧹 Удалены лишние аргументы для '{tool_name}': {dropped}")
            return cleaned
        except Exception:
            return args

    def execute_tool(self, tool_call: Dict) -> Any:
        """Выполняет инструмент"""
        try:
            logger.info(f"🔧 Выполнение инструмента: {tool_call}")

            if isinstance(tool_call, str):
                tool_call = self._extract_json_from_text(tool_call)

            if not isinstance(tool_call, dict):
                return {"error": "Некорректный формат команды инструмента"}

            name = tool_call.get("name")
            args = tool_call.get("arguments", {})

            if not name:
                return {"error": "Не указано имя инструмента"}

            logger.info(f"🛠️ Инструмент: {name}, Аргументы: {args}")

            # Маппинг инструментов на функции
            tool_functions = {
                # Браузер
                "initialize_browser": self.browser_manager.initialize_browser,
                "search_web": self.browser_manager.search_web,
                "navigate_to_url": self.browser_manager.navigate_to_url,
                "take_screenshot": self.browser_manager.take_screenshot,
                "extract_text_from_page": self.browser_manager.extract_text_from_page,
                "find_contact_info": self.browser_manager.find_contact_info,
                "click_element": self.browser_manager.click_element,
                "fill_form": self.browser_manager.fill_form,
                "scroll_page": self.browser_manager.scroll_page,
                "get_page_source": self.browser_manager.get_page_source,
                "execute_javascript": self.browser_manager.execute_javascript,
                "close_browser": self.browser_manager.close_browser,

                # Универсальные функции (теперь в command_manager)
                "take_desktop_screenshot": self.command_manager.take_desktop_screenshot,
                "take_screenshot": self.command_manager.take_desktop_screenshot,
                "click_at_coordinates": self.command_manager.click_at_coordinates,
                "click_by_coordinates": self.command_manager.click_at_coordinates, # Alias
                "move_mouse": self.command_manager.move_mouse,
                "type_text": self.command_manager.type_text,
                "press_key": self.command_manager.press_key,
                "get_screen_resolution": self.command_manager.get_screen_resolution,
                "get_mouse_position": self.command_manager.get_mouse_position,
                "get_active_window_info": self.command_manager.get_active_window_info,
                "list_windows": self.command_manager.list_windows,
                "minimize_all_windows": self.command_manager.minimize_all_windows,

                # Фабрика функций
                "create_python_script": create_python_script,
                "execute_python_script": execute_python_script,

                # Прочие функции
                "wait_for_seconds": self.command_manager.wait_for_seconds,
                "analyze_screen_region": self.command_manager.analyze_screen_region,

                # Файловая система
                "read_file": self.fs_manager.read_file,
                "write_file": self.fs_manager.write_file,
                "write_csv_file": self.fs_manager.write_csv_file,
                "delete_file": self.fs_manager.delete_file,
                "list_directory": self.fs_manager.list_directory,
                "copy_file": self.fs_manager.copy_file,
                "move_file": self.fs_manager.move_file,
                "create_directory": self.fs_manager.create_directory,
                "get_file_info": self.fs_manager.get_file_info,

                # Системные команды
                "execute_system_command": self.command_manager.execute_command,
                "open_application": self.command_manager.open_application,
                "open_application_advanced": self.command_manager.open_application_advanced,
                "find_executable": self.command_manager.find_executable,
                "close_application": self.command_manager.close_application,
                "list_processes": self.command_manager.list_processes,
                "get_system_info": self.command_manager.get_system_info,

                # Камера и звук
                "open_camera": self.command_manager.open_camera,
                "take_photo": self.command_manager.take_photo,
                "start_voice_recording": self.command_manager.start_voice_recording,
                "stop_voice_recording": self.command_manager.stop_voice_recording,

                # Анализ изображений
                "analyze_image": analyze_image,
                "locate_app_icon_on_desktop": self.command_manager.locate_app_icon_on_desktop,

                # Планировщик
                "schedule_task": self.command_manager.schedule_task,
                "schedule_recurring_task": self.command_manager.schedule_recurring_task,
                "list_scheduled_tasks": self.command_manager.list_scheduled_tasks,
                "cancel_scheduled_task": self.command_manager.cancel_scheduled_task
            }

            # Дополнительно регистрируем focus_window, если метод доступен в менеджере
            try:
                _fw = getattr(self.command_manager, "focus_window", None)
                if callable(_fw):
                    tool_functions["focus_window"] = _fw
            except Exception:
                pass

            if name not in tool_functions:
                return {"error": f"Неизвестный инструмент: {name}"}

            # Normalize argument keys for filesystem tools to match function signatures
            if isinstance(args, dict):
                arg_map = {
                    "read_file": {"path": "filepath"},
                    "write_file": {"path": "filepath"},
                    "write_csv_file": {"path": "filepath"},
                    "delete_file": {"path": "filepath"},
                    "list_directory": {"path": "dirpath"},
                    "copy_file": {"src": "source", "dst": "destination"},
                    "move_file": {"src": "source", "dst": "destination"},
                    "create_directory": {"path": "dirpath"},
                    "get_file_info": {"path": "filepath"},
                }
                if name in arg_map:
                    for old_key, new_key in arg_map[name].items():
                        if old_key in args and new_key not in args:
                            args[new_key] = args.pop(old_key)

            # Normalize argument keys for browser tools
            browser_arg_map = {
                "fill_form": {"fields": "form_fields"},
                "find_contact_info": {"selectors": "contact_types"},
                "get_page_source": {"trim": "trim_length"},
                "navigate_to_url": {"wait_selector": "wait_for_element"},
                "search_web": {"engines": "search_engines", "limit": "max_results"},
                "execute_javascript": {"code": "script", "js": "script"},
                "extract_text_from_page": {"patterns": "text_patterns", "regex": "text_patterns"},
                "scroll_page": {"величина": "amount", "направление": "direction", "pixels": "amount", "dir": "direction"},
                "click_element": {"element_selector": "selector", "element": "selector", "css_selector": "selector", "xpath": "selector"},
            }
            if name in browser_arg_map and isinstance(args, dict):
                for old_key, new_key in browser_arg_map[name].items():
                    if old_key in args and new_key not in args:
                        args[new_key] = args.pop(old_key)

            # Special handling for take_screenshot: allow combined 'path'
            if name == "take_screenshot" and isinstance(args, dict):
                if "path" in args:
                    from pathlib import Path as _P
                    p = _P(str(args.pop("path")))
                    if "filename" not in args:
                        args["filename"] = p.name
                    # only set directory if there is a real parent
                    if "directory" not in args:
                        parent = str(p.parent)
                        if parent and parent != ".":
                            args["directory"] = parent

            # For fill_form: handle 'submit' flexibly
            if name == "fill_form" and isinstance(args, dict):
                # Map 'submit' string to 'submit_selector'; boolean True triggers fallback (no selector), False disables submit
                if "submit" in args:
                    submit_val = args.pop("submit")
                    if isinstance(submit_val, str) and "submit_selector" not in args:
                        args["submit_selector"] = submit_val
                    elif isinstance(submit_val, bool):
                        if submit_val:
                            # ensure fallback by removing any existing boolean submit_selector
                            if isinstance(args.get("submit_selector"), bool):
                                args.pop("submit_selector", None)
                        else:
                            # do not submit
                            args.pop("submit_selector", None)
                # If legacy mapping created a boolean submit_selector, normalize to fallback/no submit
                if "submit_selector" in args and isinstance(args["submit_selector"], bool):
                    if args["submit_selector"]:
                        # use fallback (no explicit selector)
                        args.pop("submit_selector", None)
                    else:
                        # no submit
                        args.pop("submit_selector", None)
            # Special handling for click_element: support optional 'wait_after' without breaking signature
            post_wait_seconds = None
            if name == "click_element" and isinstance(args, dict):
                if "wait_after" in args:
                    try:
                        post_wait_seconds = float(args.get("wait_after", 0))
                    except Exception:
                        post_wait_seconds = None
                    # remove unknown param from kwargs to avoid TypeError
                    args.pop("wait_after", None)

            # Normalize argument keys for system and scheduler tools
            if isinstance(args, dict):
                system_arg_map = {
                    "close_application": {"process_name": "app_name"},
                    "list_processes": {"process_name": "name_filter"},
                }
                if name in system_arg_map:
                    for old_key, new_key in system_arg_map[name].items():
                        if old_key in args and new_key not in args:
                            args[new_key] = args.pop(old_key)

                # take_photo: combine directory+filename into output_path
                if name == "take_photo":
                    if "output_path" not in args:
                        directory = args.get("directory")
                        filename = args.get("filename")
                        try:
                            if directory and filename:
                                args["output_path"] = str(Path(directory) / filename)
                            elif filename:
                                args["output_path"] = filename
                        except Exception:
                            # ignore path composition errors; function can handle None
                            pass
                    args.pop("directory", None)
                    args.pop("filename", None)

                # start_voice_recording: this tool doesn't accept params, drop any provided args to avoid TypeError
                if name == "start_voice_recording":
                    # Remove any extraneous keys like 'duration' or 'filename'
                    args.clear()

                # schedule_task: map generic keys to expected signature
                if name == "schedule_task":
                    if "time" in args and "specific_time" not in args:
                        args["specific_time"] = args.pop("time")
                    if "delay" in args and "delay_minutes" not in args:
                        args["delay_minutes"] = args.pop("delay")
                    if "hours" in args and "delay_hours" not in args:
                        args["delay_hours"] = args.pop("hours")
                    # ensure action present
                    if "action" not in args:
                        if "command" in args:
                            args["action"] = "execute_command"
                        elif "custom_action" in args:
                            args["action"] = "custom"
                        else:
                            return {"error": "Для планировщика требуется параметр 'action' (например: 'execute_command', 'close_browser', 'take_screenshot', 'custom')"}

                # cancel_scheduled_task: accept legacy 'task_name' as numeric id
                if name == "cancel_scheduled_task":
                    if "task_name" in args and "task_id" not in args:
                        try:
                            args["task_id"] = int(args.pop("task_name"))
                        except Exception:
                            return {"error": "Параметр 'task_name' должен быть числовым ID задачи"}

            # Специальная обработка для write_csv_file
            if name == "write_csv_file" and isinstance(args, dict):
                # Нормализуем аргументы
                filepath = args.get("path") or args.get("filepath") or args.get("file_path")
                data = args.get("data") or args.get("rows") or []
                headers = args.get("headers") or args.get("columns")
                overwrite = args.get("overwrite", False)
                
                if not filepath:
                    return {"error": "Не указан путь к CSV файлу (path/filepath)"}
                if not data:
                    return {"error": "Не указаны данные для записи (data/rows)"}
                
                result = write_csv_file(filepath, data, headers, overwrite)
            else:
                # Вызов функции; поддерживаем оба формата аргументов (dict kwargs / single param)
                    # Финальная санация аргументов перед вызовом функции
                    args = self._sanitize_args(name, args or {})
                    try:
                        result = tool_functions[name](**(args or {}))
                    except TypeError:
                        # попытка передать как единый аргумент, если функция ожидает single param
                        try:
                            result = tool_functions[name](args)
                        except Exception as e:
                            raise e

                    # Нормализуем результат инструмента в единый формат
                    try:
                        result = self._normalize_tool_result(result)
                        # Логируем необработанные ключи (опционально)
                        self._log_unhandled_keys(name, result)
                    except Exception:
                        # если нормализация провалилась, сохраняем оригинал в виде ошибки
                        result = {"status": "error", "error": "result_normalization_failed", "stdout": "", "stderr": ""}

            # Apply optional wait after click if requested
            if name == "click_element" and post_wait_seconds:
                try:
                    time.sleep(post_wait_seconds)
                except Exception:
                    pass

            if isinstance(result, dict) and result.get("status") == "success":
                logger.info(f"✅ Инструмент '{name}' выполнен успешно")
            else:
                logger.warning(f"⚠️ Инструмент '{name}' завершился с предупреждением или данными")

            return result

        except Exception as e:
            logger.error(f"❌ Ошибка выполнения инструмента: {str(e)}")
            return {"error": f"Ошибка выполнения инструмента: {str(e)}"}

    def _extract_json_from_text(self, text: str) -> Any:
        """Извлекает JSON из текста, включая обработку thinking mode"""
        try:
            if not isinstance(text, str):
                text = json.dumps(text, ensure_ascii=False)
        except Exception:
            pass
        
        # Попытка прямого парсинга
        try:
            parsed = json.loads(text)
            # Если это уже массив - возвращаем
            if isinstance(parsed, list):
                return parsed
            # Если это объект, ищем в нем массив плана
            if isinstance(parsed, dict):
                # Проверяем поле "thinking" (thinking mode)
                if "thinking" in parsed:
                    thinking = parsed["thinking"]
                    if isinstance(thinking, str):
                        try:
                            thinking_obj = json.loads(thinking)
                            if isinstance(thinking_obj, list):
                                return thinking_obj
                            if isinstance(thinking_obj, dict):
                                if "plan" in thinking_obj and isinstance(thinking_obj["plan"], list):
                                    return thinking_obj["plan"]
                                if "steps" in thinking_obj and isinstance(thinking_obj["steps"], list):
                                    return thinking_obj["steps"]
                        except (json.JSONDecodeError, TypeError):
                            pass
                # Проверяем другие возможные поля
                for key in ["plan", "steps", "response"]:
                    if key in parsed and isinstance(parsed[key], list):
                        return parsed[key]
                # Если это похоже на один шаг плана — оборачиваем в массив
                if ("tool" in parsed or "name" in parsed) and ("args" in parsed or "description" in parsed or "step" in parsed):
                    return [parsed]
            return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        try:
            # Очистка кодовых блоков и комментариев
            cleaned = re.sub(r'^```json\s*|^```\s*|```\s*$', '', text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r'//.*$', '', cleaned, flags=re.MULTILINE)
            cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
            cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned)
            
            # Попытка парсинга очищенного текста
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    # Ищем массив в объекте
                    for key in ["plan", "steps", "response", "thinking"]:
                        if key in parsed:
                            value = parsed[key]
                            if isinstance(value, list):
                                return value
                            if isinstance(value, str):
                                try:
                                    nested = json.loads(value)
                                    if isinstance(nested, list):
                                        return nested
                                    if isinstance(nested, dict) and "plan" in nested and isinstance(nested["plan"], list):
                                        return nested["plan"]
                                except (json.JSONDecodeError, TypeError):
                                    pass
                    # Один шаг — завернуть в массив
                    if ("tool" in parsed or "name" in parsed) and ("args" in parsed or "description" in parsed or "step" in parsed):
                        return [parsed]
            except (json.JSONDecodeError, TypeError):
                pass

            # Поиск JSON объекта в тексте
            obj_match = re.search(r'\{[\s\S]*?\}', cleaned, re.DOTALL)
            if obj_match:
                obj_str = obj_match.group(0)
                try:
                    obj = json.loads(obj_str)
                    if isinstance(obj, dict):
                        # Ищем массив плана в объекте
                        for key in ["plan", "steps", "response"]:
                            if key in obj and isinstance(obj[key], list):
                                return obj[key]
                        # Если есть thinking, пытаемся распарсить
                        if "thinking" in obj and isinstance(obj["thinking"], str):
                            try:
                                thinking_obj = json.loads(obj["thinking"])
                                if isinstance(thinking_obj, list):
                                    return thinking_obj
                                if isinstance(thinking_obj, dict) and "plan" in thinking_obj:
                                    return thinking_obj["plan"]
                            except (json.JSONDecodeError, TypeError):
                                pass
                        # Один шаг — завернуть в массив
                        if ("tool" in obj or "name" in obj) and ("args" in obj or "description" in obj or "step" in obj):
                            return [obj]
                        return obj
                except (json.JSONDecodeError, TypeError):
                    pass

            # Поиск массива шагов (приоритет - ищем самый большой массив)
            arr_matches = list(re.finditer(r'\[[\s\S]*?\]', cleaned, re.DOTALL))
            if arr_matches:
                # Берем самый длинный массив (скорее всего это план)
                arr_match = max(arr_matches, key=lambda m: len(m.group(0)))
                arr_str = arr_match.group(0)
                try:
                    arr = json.loads(arr_str)
                    if isinstance(arr, list) and len(arr) > 0:
                        # Проверяем, что это действительно массив шагов
                        if isinstance(arr[0], dict) and ("tool" in arr[0] or "name" in arr[0]):
                            return arr
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception as e:
            logger.warning(f"⚠️ Ошибка извлечения JSON: {e}")

        # Попытка восстановления усеченного JSON
        try:
            t = text.strip()
            def _balance_brackets(s: str) -> str:
                open_curly = s.count('{')
                close_curly = s.count('}')
                open_sq = s.count('[')
                close_sq = s.count(']')
                fixed = s
                # закрываем сначала фигурные, затем квадратные
                if close_curly < open_curly:
                    fixed += '}' * (open_curly - close_curly)
                if close_sq < open_sq:
                    fixed += ']' * (open_sq - close_sq)
                return fixed

            if t.startswith('{') or t.startswith('['):
                fixed = _balance_brackets(t)
                try:
                    parsed = json.loads(fixed)
                    if isinstance(parsed, dict):
                        if ("tool" in parsed or "name" in parsed) and ("args" in parsed or "description" in parsed or "step" in parsed):
                            return [parsed]
                        for key in ["plan", "steps"]:
                            if key in parsed and isinstance(parsed[key], list):
                                return parsed[key]
                        return parsed
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
        except Exception:
            pass

        return text

    def _build_tool_prompt(self, tool_name: str, args: Dict[str, Any], step_desc: str) -> Optional[str]:
        try:
            p = self.prompts
            if tool_name == "navigate_to_url":
                tmpl = p.get("browser_automation", {}).get("navigation")
                if tmpl:
                    return tmpl.format(url=args.get("url", ""), target_element=args.get("wait_for_element", ""))
            if tool_name == "fill_form":
                tmpl = p.get("browser_automation", {}).get("form_filling")
                if tmpl:
                    return tmpl.format(form_fields=json.dumps(args.get("form_fields", {}), ensure_ascii=False), form_values=json.dumps(args.get("form_fields", {}), ensure_ascii=False), submit_button=args.get("submit_selector", ""))
            if tool_name == "extract_text_from_page":
                tmpl = p.get("browser_automation", {}).get("data_extraction")
                if tmpl:
                    return tmpl.format(data_type="text", selectors=json.dumps(args.get("selectors", ["body"]), ensure_ascii=False), output_file=args.get("output_file", ""), format=args.get("format", "text"))
            if tool_name == "schedule_task":
                tmpl = p.get("scheduled_task_parsing", {}).get("template")
                if tmpl:
                    return tmpl.format(user_request=step_desc)
            if tool_name in ("execute_system_command", "open_application", "close_application"):
                app_tmpl = p.get("command_generation", {}).get("application")
                win_tmpl = p.get("command_generation", {}).get("windows")
                if tool_name == "execute_system_command" and win_tmpl:
                    return win_tmpl.format(task=step_desc)
                if app_tmpl:
                    action = "open" if tool_name == "open_application" else "close"
                    return app_tmpl.format(action=action, app_name=args.get("app_name", ""))
            if tool_name == "search_web":
                q = args.get("query", step_desc)
                return f"Подготовь точные JSON аргументы для инструмента 'search_web' по запросу '{q}'. Верни только JSON: {{\"arguments\": {{\"search_engines\": [\"google\", \"bing\"], \"max_results\": 5}}}}"
        except Exception:
            return None
        return None

    def _refine_step_args_with_model(self, tool_name: str, args: Dict[str, Any], step_desc: str) -> Dict[str, Any]:
        # Нормализуем URL для navigate_to_url перед обработкой
        if tool_name == "navigate_to_url" and args and "url" in args:
            url = str(args["url"]).strip()
            if not url.startswith(('http://', 'https://')) and '.' in url and not url.startswith('/'):
                args["url"] = f"https://{url}"
                logger.info(f"🔧 URL нормализован перед уточнением: {args['url']}")
        
        prompt = self._build_tool_prompt(tool_name, args or {}, step_desc or "")
        if not prompt:
            return args or {}
        resp = call_ollama(prompt, fast=True, options={"temperature": 0.2, "num_predict": 512}, format="json")
        parsed = self._extract_json_from_text(resp)
        try:
            if isinstance(parsed, dict):
                if tool_name == "schedule_task":
                    new_args = {}
                    for k in ("action", "delay_minutes", "delay_hours", "specific_time", "command", "filename", "custom_action"):
                        if k in parsed:
                            new_args[k] = parsed.get(k)
                    args.update(new_args)
                    return args
                if "arguments" in parsed and isinstance(parsed["arguments"], dict):
                    args.update(parsed["arguments"])
                    # Нормализуем URL после обновления
                    if tool_name == "navigate_to_url" and "url" in args:
                        url = str(args["url"]).strip()
                        if not url.startswith(('http://', 'https://')) and '.' in url and not url.startswith('/'):
                            args["url"] = f"https://{url}"
                            logger.info(f"🔧 URL нормализован после уточнения: {args['url']}")
                    return args
                if "args" in parsed and isinstance(parsed["args"], dict):
                    args.update(parsed["args"])
                    # Нормализуем URL после обновления
                    if tool_name == "navigate_to_url" and "url" in args:
                        url = str(args["url"]).strip()
                        if not url.startswith(('http://', 'https://')) and '.' in url and not url.startswith('/'):
                            args["url"] = f"https://{url}"
                            logger.info(f"🔧 URL нормализован после уточнения: {args['url']}")
                    return args
                args.update(parsed)
                # Нормализуем URL после обновления
                if tool_name == "navigate_to_url" and "url" in args:
                    url = str(args["url"]).strip()
                    if not url.startswith(('http://', 'https://')) and '.' in url and not url.startswith('/'):
                        args["url"] = f"https://{url}"
                        logger.info(f"🔧 URL нормализован после уточнения: {args['url']}")
                return args
        except Exception:
            # Нормализуем URL даже при ошибке парсинга
            if tool_name == "navigate_to_url" and args and "url" in args:
                url = str(args["url"]).strip()
                if not url.startswith(('http://', 'https://')) and '.' in url and not url.startswith('/'):
                    args["url"] = f"https://{url}"
                    logger.info(f"🔧 URL нормализован при ошибке парсинга: {args['url']}")
            return args or {}
        # Нормализуем URL перед возвратом
        if tool_name == "navigate_to_url" and args and "url" in args:
            url = str(args["url"]).strip()
            if not url.startswith(('http://', 'https://')) and '.' in url and not url.startswith('/'):
                args["url"] = f"https://{url}"
                logger.info(f"🔧 URL нормализован перед возвратом: {args['url']}")
        return args or {}

    def _ask_model_next_step(self, original_task: str, executed_steps: List[Dict]) -> Optional[Dict]:
        try:
            p = self.prompts.get("task_planning", {}).get("template")
            if not p:
                return None
            history = []
            for s in executed_steps[-5:]:
                try:
                    status = str(s.get("status", "")).lower()
                    desc = s.get("description", "")
                    tool = s.get("tool") or s.get("name") or ""
                    history.append({"status": status, "description": desc, "tool": tool})
                except Exception:
                    continue
            prompt = f"ЗАДАЧА: {original_task}\nИстория: {json.dumps(history, ensure_ascii=False)}\nВерни ТОЛЬКО один следующий шаг в виде JSON массива длиной 1."
            resp = call_ollama(prompt, fast=True, options={"temperature": 0.1, "num_predict": 256}, format="json")
            data = self._extract_json_from_text(resp)
            if isinstance(data, list) and data:
                it = data[0]
                if isinstance(it, dict) and it.get("tool"):
                    return it
            return None
        except Exception:
            return None

    def _post_verify_ui_step(self, tool_name: str, args: Dict[str, Any], step_result: Dict[str, Any]) -> None:
        try:
            # Веб-проверки через браузерный скриншот (как было)
            if tool_name in {"navigate_to_url", "fill_form", "click_element"}:
                fname = f"verify_{step_result.get('step')}_{int(time.time())}.png"
                shot = self.browser_manager.take_screenshot(filename=fname)
                if isinstance(shot, dict) and shot.get("error"):
                    step_result["verification"] = {"status": "error", "error": shot.get("error")}
                    return
                path = shot.get("file_path") if isinstance(shot, dict) else None
                tmpl = self.prompts.get("image_analysis", {}).get("screen_verification")
                if not tmpl:
                    step_result["verification"] = {"status": "skipped", "reason": "no template"}
                    return
                elements = []
                expected = ""
                if tool_name == "navigate_to_url":
                    sel = (args or {}).get("wait_for_element") or "body"
                    elements = [sel]
                    expected = "страница загружена"
                elif tool_name == "fill_form":
                    elements = list(((args or {}).get("form_fields") or {}).keys())
                    expected = "форма отправлена"
                else:
                    elements = [((args or {}).get("selector") or "")]
                    expected = "элемент нажат"
                question = tmpl.format(elements=", ".join([e for e in elements if e]), expected_state=expected, screenshot_path=path)
                analysis = analyze_image(str(path), question) if path else {"error": "no_image"}
                step_result["verification"] = {"status": "done", "image_path": path, "analysis": analysis}
                return

            # Политика верификации
            if str(self.gui_verify_policy).lower() == "never":
                return

            # Десктоп-проверка для клика по координатам: делаем общий скриншот и анализируем регион вокруг клика
            if tool_name == "click_at_coordinates" and isinstance(args, dict):
                x = int(args.get("x", -1))
                y = int(args.get("y", -1))
                if x >= 0 and y >= 0:
                    # Для on_failure политика: верифицируем только если шаг помечен как failed (у нас вызывается на success) — пропускаем
                    if str(self.gui_verify_policy).lower() == "on_failure" and str(step_result.get("status", "")).lower() == "success":
                        return
                    # Делаем скриншот рабочего стола
                    shot = self.execute_tool({"name": "take_desktop_screenshot", "arguments": {"filename": f"verify_click_{int(time.time())}.png"}})
                    if not isinstance(shot, dict) or shot.get("status") != "success":
                        step_result["verification"] = {"status": "error", "error": "screenshot_failed"}
                    # Анализируем небольшой регион вокруг точки клика (радиус из конфигурации)
                    r = max(20, int(self.gui_verify_radius))
                    rx, ry, rw, rh = self._clamp_region(x - r, y - r, 2 * r, 2 * r)
                    question = (
                        "Подтверди, что в указанной области находится ожидаемый элемент для клика (фокус/подсветка/"
                        "каретка ввода/контакт). Ответь кратко: yes или no."
                    )
                    analysis = self.execute_tool({
                        "name": "analyze_screen_region",
                        "arguments": {"x": rx, "y": ry, "width": rw, "height": rh, "question": self._format_coordinate_question(question, "verify")}
                    })
                    step_result["verification"] = {"status": "done", "region": {"x": rx, "y": ry, "width": rw, "height": rh}, "analysis": analysis}

                    # Быстрая перефокусировка и повторный клик, если ответ не подтверждён
                    try:
                        attempts = 0
                        ok = False
                        if isinstance(analysis, dict):
                            ok, coords_json, raw_text = self._extract_coordinate_analysis(analysis)
                            if not ok:
                                atext = raw_text.lower()
                                ok = "yes" in atext and "no" not in atext
                            if not ok and coords_json:
                                try:
                                    c = coords_json[0]
                                    nx_json, ny_json = int(c.get("x")), int(c.get("y"))
                                    self.execute_tool({"name": "click_at_coordinates", "arguments": {"x": nx_json, "y": ny_json}})
                                    step_result.setdefault("verification_attempts", []).append({
                                        "coords": {"x": nx_json, "y": ny_json},
                                        "region": {"x": rx, "y": ry, "width": rw, "height": rh},
                                        "analysis": analysis,
                                        "ok": True,
                                        "from": "analysis_json"
                                    })
                                    return
                                except Exception:
                                    pass
                        if not ok and self.gui_refocus_retry:
                            for dx, dy in self.gui_refocus_offsets:
                                if attempts >= self.gui_verify_max_attempts:
                                    break
                                nx, ny = x + dx, y + dy
                                # совершаем повторный клик
                                self.execute_tool({"name": "click_at_coordinates", "arguments": {"x": nx, "y": ny}})
                                self.execute_tool({"name": "wait_for_seconds", "arguments": {"seconds": 0.25}})
                                # повторная верификация
                                r = max(20, int(self.gui_verify_radius))
                                rx, ry, rw, rh = self._clamp_region(nx - r, ny - r, 2 * r, 2 * r)
                                analysis2 = self.execute_tool({
                                    "name": "analyze_screen_region",
                                    "arguments": {"x": rx, "y": ry, "width": rw, "height": rh, "question": self._format_coordinate_question(question, "verify")}
                                })
                                ok, coords_json, raw_text = self._extract_coordinate_analysis(analysis2)
                                if not ok:
                                    a2text = raw_text.lower()
                                    ok = "yes" in a2text and "no" not in a2text
                                if not ok and coords_json:
                                    try:
                                        c = coords_json[0]
                                        nx2, ny2 = int(c.get("x")), int(c.get("y"))
                                        self.execute_tool({"name": "click_at_coordinates", "arguments": {"x": nx2, "y": ny2}})
                                        step_result.setdefault("verification_attempts", []).append({
                                            "coords": {"x": nx2, "y": ny2},
                                            "region": {"x": rx, "y": ry, "width": rw, "height": rh},
                                            "analysis": analysis2,
                                            "ok": True,
                                            "from": "analysis_json"
                                        })
                                        return
                                    except Exception:
                                        pass
                                step_result.setdefault("verification_attempts", []).append({
                                    "coords": {"x": nx, "y": ny},
                                    "region": {"x": rx, "y": ry, "width": rw, "height": rh},
                                    "analysis": analysis2,
                                    "ok": ok,
                                })
                                attempts += 1
                                if ok:
                                    break
                        if not ok:
                            step_result.setdefault("verification", {}).update({"status": "warning", "error": "max_gui_verify_attempts"})
                    except Exception:
                        pass
        except Exception as e:
            step_result["verification"] = {"status": "error", "error": str(e)}

    def analyze_task(self, task_description: str) -> str:
        """Анализирует тип задачи"""
        task_lower = task_description.lower()

        categories = self.instructions.get("task_analysis", {}).get("categories", {})

        for category, info in categories.items():
            keywords = info.get("keywords", [])
            if any(keyword in task_lower for keyword in keywords):
                logger.info(f"📋 Категория задачи: {category}")
                return category

        logger.info("📋 Категория задачи: complex (сложная)")
        return "complex"

    def _should_show_browser(self, task_description: str) -> bool:
        """Определяет, нужно ли показывать браузер (не headless) на основе задачи"""
        task_lower = task_description.lower()
        visible_keywords = [
            "я должен увидеть", "должен видеть", "видеть", "покажи", "показать",
            "на рабочем столе", "на экране", "отображение", "визуально",
            "открой окно", "покажи окно", "видимое", "видимый"
        ]
        return any(keyword in task_lower for keyword in visible_keywords)

    def _should_use_existing_browser(self, task_description: str) -> bool:
        task_lower = task_description.lower()
        markers = ["использую открытый браузер", "использовать открытый браузер", "открытый браузер"]
        if any(m in task_lower for m in markers):
            return True
        try:
            windows = self.command_manager.list_windows()
            if isinstance(windows, dict) and windows.get("status") == "success":
                for w in windows.get("windows", []):
                    name = str(w.get("ProcessName", "")).lower()
                    title = str(w.get("MainWindowTitle", "")).lower()
                    if any(b in name for b in ["chrome", "msedge", "firefox"]) or any(t in title for t in ["chrome", "edge", "mozilla", "youtube"]):
                        return True
        except Exception:
            pass
        return False

    def analyze_task_requirements(self, task_description: str) -> Dict[str, Any]:
        """Анализирует задачу и определяет необходимые функции/категории"""
        logger.info("🔍 Этап 1: Анализ требований задачи...")
        
        # Определяем, нужно ли показывать браузер
        show_browser = self._should_show_browser(task_description)
        
        # Формируем список всех доступных инструментов с категориями
        all_tools_info = []
        categories_info = self.instructions.get("task_analysis", {}).get("categories", {})
        
        for tool in self.tools:
            tool_name = tool.get("name", "")
            tool_desc = tool.get("description", "")
            tool_params = tool.get("parameters", {})
            
            # Определяем категорию инструмента
            tool_category = "other"
            for cat_name, cat_info in categories_info.items():
                if tool_name in cat_info.get("tools", []):
                    tool_category = cat_name
                    break
            
            all_tools_info.append({
                "name": tool_name,
                "description": tool_desc,
                "category": tool_category,
                "parameters": list(tool_params.keys())[:15]
            })
        
        tools_json = json.dumps(all_tools_info, ensure_ascii=False, indent=2)
        
        browser_note = ""
        if show_browser:
            browser_note = "\n⚠️ CRITICALLY IMPORTANT: The user wants to SEE the browser on the desktop! For initialize_browser, use headless: false."
        
        analysis_prompt = f"""Ты - AI агент который анализирует задачи и определяет стратегию их выполнения. Ты должен найти решение ЛЮБОЙ задачи, даже если для неё нет прямых инструментов.

    ЗАДАЧА ПОЛЬЗОВАТЕЛЯ: {task_description}
    {browser_note}

    ТВОЯ ЦЕЛЬ: проанализировать задачу и определить стратегию решения. ВАЖНО: ты ДОЛЖЕН найти решение, даже если для этого потребуется:

    1. Создать новые функции или скрипты
    2. Использовать комбинации существующих инструментов
    3. Использовать скриншоты + анализ изображений для взаимодействия с интерфейсом (учитывай разные размеры/масштабы экранов)
    4. Выполнять системные команды Windows напрямую
    5. Искать альтернативные подходы

    ДОСТУПНЫЕ ФУНКЦИИ:
    {tools_json}

    КРИТИЧЕСКИ ВАЖНЫЕ СТРАТЕГИИ ДЛЯ СЛОЖНЫХ ЗАДАЧ:
    - Если нет функции для нужного действия: используй take_screenshot + analyze_image чтобы "увидеть" интерфейс и понять как действовать
    - Для кликов по элементам без селекторов: используй анализ изображения чтобы найти координаты, затем предложи новую функцию click_by_coordinates
    - Для работы с нестандартными приложениями: используй execute_system_command с PowerShell или cmd
    - Для обработки данных: используй комбинацию read_file + analyze_image (для визуальных данных) или создай Python скрипт
    - Для автоматизации GUI: используй последовательность скриншотов и анализа для определения состояния интерфейса
    - При кликах по координатам: сначала найди координаты через analyze_screen_region, затем после клика сделай верификацию малого региона вокруг точки
    - Учитывай разрешение экрана/активного окна: координаты и регионы должны зависеть от текущих размеров

    Верни JSON в формате:
    {{
    "required_categories": ["категории"],
    "required_functions": ["основные_функции"],
    "alternative_approaches": ["резервные_стратегии"],
    "approach": "подробное описание подхода",
    "new_functions_needed": [
        {{
        "name": "имя_новой_функции", 
        "description": "что делает",
        "implementation": "как реализовать (python, command, etc)",
        "reason": "почему нужна"
        }}
    ],
    "screenshot_based_solution": true/false, # требуется ли анализ через скриншоты
    "command_based_solution": true/false, # требуется ли использование команд
    "complexity": "simple|medium|complex",
    "estimated_steps": число
    }}

    Верни ТОЛЬКО JSON."""

        logger.info("🧠 Запрос к модели для анализа требований...")
        try:
            logger.info(f"📏 Длина промпта анализа: {len(analysis_prompt)} символов")
        except Exception:
            pass
        response = call_ollama(analysis_prompt, fast=True, options={"temperature": 0.2, "num_predict": 512}, format="json")
        
        try:
            analysis = self._extract_json_from_text(response)
            if isinstance(analysis, dict):
                logger.info(f"✅ Анализ завершен:")
                logger.info(f"   Категории: {analysis.get('required_categories', [])}")
                logger.info(f"   Функции: {analysis.get('required_functions', [])}")
                logger.info(f"   Подход: {analysis.get('approach', 'не указан')}")
                if analysis.get('new_functions_needed'):
                    logger.info(f"   ⚠ Требуются новые функции: {len(analysis['new_functions_needed'])}")
                return analysis
            else:
                logger.warning("⚠️ Не удалось распарсить анализ, используем базовый подход")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка анализа требований: {e}")
        
        # Fallback: базовый анализ
        category = self.analyze_task(task_description)
        return {
            "required_categories": [category],
            "required_functions": [],
            "approach": "стандартный подход",
            "new_functions_needed": [],
            "complexity": category,
            "estimated_steps": 3
        }

    def create_task_plan(self, task_description: str) -> List[Dict]:
        """Создаёт план выполнения задачи"""
        logger.info("📋 Создание плана выполнения задачи.")

        # Этап 1: Анализ требований задачи
        requirements = self.analyze_task_requirements(task_description)
        
        # Этап 2: Выбор инструментов на основе анализа
        required_functions = requirements.get("required_functions", [])
        required_categories = requirements.get("required_categories", [])
        
        name_to_tool = {t.get("name"): t for t in self.tools}
        selected = []
        
        # Добавляем функции, указанные в анализе
        for func_name in required_functions:
            if func_name in name_to_tool:
                selected.append(name_to_tool[func_name])
        
        # Добавляем функции из требуемых категорий
        categories_info = self.instructions.get("task_analysis", {}).get("categories", {})
        for cat_name in required_categories:
            cat_tools = categories_info.get(cat_name, {}).get("tools", [])
            for tool_name in cat_tools:
                if tool_name in name_to_tool and name_to_tool[tool_name] not in selected:
                    selected.append(name_to_tool[tool_name])
        
        # Если ничего не выбрано, используем базовый набор
        if not selected:
            baseline = ["read_file", "initialize_browser", "navigate_to_url", "extract_text_from_page", "take_screenshot",
                        "analyze_image", "write_file", "execute_system_command", "open_application", 
                        "close_application", "search_web", "fill_form", "click_element", "schedule_task"]
            selected = [name_to_tool[n] for n in baseline if n in name_to_tool]

        # Приоритизация ключевых инструментов (для лучшего выбора моделью)
        preferred_order = ["read_file", "initialize_browser", "navigate_to_url", "extract_text_from_page", 
                           "take_screenshot", "analyze_image", "write_file", "execute_system_command",
                           "open_application", "close_application"]
        order_map = {name: idx for idx, name in enumerate(preferred_order)}
        try:
            selected.sort(key=lambda t: order_map.get(t.get("name", ""), 999))
        except Exception:
            pass
        
        def _tool_line(t: Dict[str, Any]) -> str:
            name = t.get('name', '')
            desc = t.get('description', '')
            params = t.get('parameters', {})
            param_keys = ", ".join(list(params.keys())[:4])
            return f"- {name}: {desc} (args: {param_keys})"

        # Компактный манифест всех инструментов (имя + ключи параметров)
        try:
            all_tools = self.tools if isinstance(self.tools, list) else []
        except Exception:
            all_tools = []

        def _tool_manifest_line(t: Dict[str, Any]) -> str:
            name = t.get('name', '')
            params = t.get('parameters', {})
            keys = ", ".join(list(params.keys())[:4])
            return f"- {name}({keys})"

        tools_manifest = "\n".join([_tool_manifest_line(t) for t in all_tools])
        if len(tools_manifest) > 3000:
            tools_manifest = tools_manifest[:3000] + "\n..."

        # Фокусный список: только отобранные, с кратким описанием
        tools_desc = "\n".join([_tool_line(t) for t in selected[:12]])
        if len(tools_desc) > 1800:
            tools_desc = tools_desc[:1800] + "\n..."
        
        logger.info(f"🤖 Модель будет выбирать из {len(selected)} доступных инструментов")
        logger.info(f"📋 Подход: {requirements.get('approach', 'стандартный')}")
        
        # Если требуются новые функции, добавляем информацию о них
        new_functions_info = ""
        if requirements.get("new_functions_needed"):
            new_funcs = requirements["new_functions_needed"]
            new_functions_info = "\n\n⚠️ ВНИМАНИЕ: Для выполнения задачи могут потребоваться новые функции:\n"
            for nf in new_funcs:
                new_functions_info += f"- {nf.get('name', 'неизвестно')}: {nf.get('description', '')} ({nf.get('reason', '')})\n"
            new_functions_info += "\nПопробуй найти решение используя существующие функции, но если это невозможно - укажи это в плане."

        # Определяем, нужно ли показывать браузер
        show_browser = self._should_show_browser(task_description)
        browser_warning = ""
        if show_browser:
            browser_warning = "\n⚠️ КРИТИЧЕСКИ ВАЖНО: Пользователь хочет ВИДЕТЬ браузер на рабочем столе! Для initialize_browser используй headless: false или не указывай headless (по умолчанию false)."
        
        # Улучшенный промпт с четкими инструкциями
        prompt = f"""Ты - AI-агент, который планирует выполнение задач. 

ЗАДАЧА: {task_description}
{browser_warning}

АНАЛИЗ ЗАДАЧИ:
- Подход: {requirements.get('approach', 'стандартный')}
- Ожидаемая сложность: {requirements.get('complexity', 'medium')}
- Примерное количество шагов: {requirements.get('estimated_steps', 3)}
{new_functions_info}

ТВОЯ РАБОТА: Создай детальный план выполнения задачи в виде JSON массива шагов.

ВАЖНО: Верни ТОЛЬКО JSON массив, без дополнительного текста, без пояснений, без markdown блоков.

ФОРМАТ ОТВЕТА (строго соблюдай):
[
  {{
    "step": 1,
    "description": "краткое описание шага на русском",
    "tool": "имя_инструмента",
    "args": {{
      "параметр1": "значение1",
      "параметр2": "значение2"
    }}
  }},
  {{
    "step": 2,
    "description": "следующий шаг",
    "args": {{}}
  }}
]

  ПОДСКАЗКИ ПО ВЫБОРУ ИНСТРУМЕНТОВ:
  - Для чтения/записи файлов: используй read_file / write_file.
  - Для перехода по ссылкам: initialize_browser (headless: false по умолчанию) → navigate_to_url.
  - Для извлечения текста: extract_text_from_page, при отсутствии селекторов — take_screenshot + analyze_image.
  - Для системных действий: execute_system_command. Для запуска приложений: open_application.

  ВСЕ ДОСТУПНЫЕ ИНСТРУМЕНТЫ (справочник):
  {tools_manifest}

  ФОКУСНЫЕ ИНСТРУМЕНТЫ (используй в первую очередь):
  {tools_desc}

2. ДЛЯ РАБОТЫ С ИНТЕРФЕЙСОМ:
   - Используй take_desktop_screenshot/analyze_screen_region чтобы "увидеть" что на экране
   - Анализируй скриншоты чтобы найти нужные элементы, всегда учитывая реальное разрешение/масштаб
   - Используй координаты если нет селекторов; после клика верифицируй область вокруг точки (малый регион) и при необходимости повтори клик для перефокуса

3. ДЛЯ СИСТЕМНЫХ ЗАДАЧ:
   - Используй execute_system_command с PowerShell
   - Для поиска файлов: Get-ChildItem, dir
   - Для управления процессами: tasklist, taskkill
   - Для работы с реестром: reg

4. ДЛЯ АВТОМАТИЗАЦИИ:
   - Создавай временные Python скрипты для сложных операций
   - Используй итеративный подход для множества элементов
   - Сохраняй промежуточные результаты

5. КРИТИЧЕСКИ ВАЖНО: 
   - НЕ говори "невозможно" - ВСЕГДА ищи решение
   - Используй комбинации инструментов
   - Предлагай новые функции когда нужно
   - Используй скриншоты как универсальный инструмент взаимодействия.
   
КРИТИЧЕСКИ ВАЖНО: Задача "{task_description}" требует выполнения ВСЕХ частей. Создай план, который покрывает ВСЕ требования задачи.

Верни ТОЛЬКО JSON массив, начинающийся с [ и заканчивающийся ]."""

        logger.info("🧠 Запрос к модели для создания плана...")
        try:
            logger.info(f"📏 Длина промпта плана: {len(prompt)} символов")
        except Exception:
            pass
        response = call_ollama(prompt, fast=True, options={"temperature": 0.2, "num_predict": 512}, format="json")
        
        try:
            snippet = str(response)[:300]
            logger.info(f"🔎 Ответ модели (первые 300 симв.): {snippet}")
        except Exception:
            pass

        try:
            plan = self._extract_json_from_text(response)
            
            # Если план - строка, пытаемся распарсить её как JSON
            if isinstance(plan, str):
                try:
                    plan = json.loads(plan)
                    logger.info("🔄 JSON распарсен из строки")
                except json.JSONDecodeError:
                    # Пытаемся найти JSON в строке
                    import re
                    json_match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', plan)
                    if json_match:
                        try:
                            plan = json.loads(json_match.group(0))
                            logger.info("🔄 JSON извлечен из строки")
                        except json.JSONDecodeError:
                            # Попробуем восстановить усеченный JSON
                            snippet = json_match.group(0)
                            fixed = None
                            if snippet.strip().startswith('{') and not snippet.strip().endswith('}'):
                                fixed = snippet + '}'
                            elif snippet.strip().startswith('[') and not snippet.strip().endswith(']'):
                                fixed = snippet + ']'
                            if fixed:
                                try:
                                    plan = json.loads(fixed)
                                    logger.info("🔄 JSON восстановлен из усеченного ответа")
                                except json.JSONDecodeError:
                                    logger.error(f"❌ Не удалось распарсить JSON из строки: {plan[:200]}")
                                    plan = None
            
            # Если модель вернула один объект вместо массива, оборачиваем в массив
            if isinstance(plan, dict):
                # Проверяем, что это похоже на шаг плана
                if "tool" in plan or "name" in plan:
                    logger.info("🔄 Модель вернула один шаг, оборачиваем в массив")
                    plan = [plan]
                else:
                    # Если это объект с другими полями, пытаемся извлечь план
                    if "plan" in plan and isinstance(plan["plan"], list):
                        plan = plan["plan"]
                    elif "steps" in plan and isinstance(plan["steps"], list):
                        plan = plan["steps"]
                    else:
                        logger.warning("⚠️ Неожиданный формат ответа, пытаемся преобразовать")
                        plan = [plan]
            
            if isinstance(plan, list) and len(plan) > 0:
                # Валидация плана
                valid_plan = []
                for idx, step in enumerate(plan):
                    if isinstance(step, dict):
                        tool_name = step.get("tool") or step.get("name")
                        if tool_name:
                            # Проверяем, что инструмент существует
                            if any(t.get("name") == tool_name for t in self.tools):
                                valid_plan.append(step)
                                logger.info(f"  ✓ Шаг {step.get('step', idx+1)}: {tool_name} - {step.get('description', '')}")
                            else:
                                logger.warning(f"  ⚠ Шаг {step.get('step', idx+1)}: неизвестный инструмент '{tool_name}'")
                        else:
                            logger.warning(f"  ⚠ Шаг {idx+1}: не указан инструмент")
                
                if valid_plan:
                    logger.info(f"✅ План создан моделью: {len(valid_plan)} шагов")
                    return valid_plan
                else:
                    logger.warning("⚠️ План не содержит валидных шагов")
            else:
                logger.error(f"❌ План не является массивом. Тип: {type(plan)}, значение: {str(plan)[:200]}")
            
            # Fallback: повторный запрос с более строгими инструкциями
            logger.info("🔄 Повторный запрос с упрощенным промптом...")
            fallback_prompt = f"""ЗАДАЧА: {task_description}

Верни ТОЛЬКО JSON массив шагов. Формат:
[{{"step": 1, "description": "описание", "tool": "имя_инструмента", "args": {{}}}}, {{"step": 2, ...}}]

ВАЖНО: Верни МАССИВ шагов, даже если шаг один - оберни его в квадратные скобки [].

Доступные инструменты:
{tools_desc}

Верни массив, начинающийся с [ и заканчивающийся ]."""

            resp2 = call_ollama(fallback_prompt, fast=False, options={"temperature": 0.2, "num_predict": 1024}, format="json")
            plan2 = self._extract_json_from_text(resp2)
            
            # Обрабатываем случай, когда вернулся один объект
            if isinstance(plan2, dict):
                if "tool" in plan2 or "name" in plan2:
                    logger.info("🔄 Fallback: модель вернула один шаг, оборачиваем в массив")
                    plan2 = [plan2]
            
            if isinstance(plan2, list) and len(plan2) > 0:
                logger.info(f"✅ План (fallback) создан: {len(plan2)} шагов")
                return plan2
            
            # Последний fallback: правило-ориентированный план
            logger.info("🔄 Использование правило-ориентированного плана...")
            rb = self._rule_based_plan(task_description)
            if rb:
                logger.info(f"✅ Правило-ориентированный план создан: {len(rb)} шагов")
                return rb
            
            logger.error("❌ Не удалось создать план ни одним способом")
            return []
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания плана: {str(e)}")
            import traceback
            logger.debug(f"Трассировка: {traceback.format_exc()}")
            return []

    def _fix_failed_step(self, original_task: str, failed_step: Dict, executed_steps: List[Dict]) -> Optional[Dict]:
        """Анализирует ошибку и запрашивает исправление у модели с созданием новых функций"""
        logger.info("🔧 Анализ ошибки и запрос исправления...")
        
        error_msg = str(failed_step.get("result", {}).get("error", ""))
        tool_name = failed_step.get("tool") or failed_step.get("name", "")
        step_desc = failed_step.get("description", "")
        step_args = failed_step.get("args", {})
        
        # Формируем контекст
        steps_summary = []
        for step in executed_steps[-3:]:
            tool = step.get("tool") or step.get("name", "неизвестно")
            desc = step.get("description", "")
            status = step.get("status", "unknown")
            steps_summary.append(f"- {tool}: {desc} (статус: {status})")
        
        context = "\n".join(steps_summary)
        
        fix_prompt = f"""Ты - AI-агент, который исправляет ошибки и находит решения ЛЮБЫМИ способами.

    ИСХОДНАЯ ЗАДАЧА: {original_task}

    ПРОВАЛИВШИЙСЯ ШАГ:
    - Инструмент: {tool_name}
    - Ошибка: {error_msg}

    ТВОЯ ЗАДАЧА: Найди решение, даже если для этого нужно:
    1. Создать новую функцию
    2. Использовать системные команды  
    3. Использовать скриншоты и анализ изображений
    4. Написать Python скрипт
    5. Использовать координаты вместо селекторов

    ВАЖНЫЕ РЕСУРСЫ:
    - Всегда можно использовать take_screenshot + analyze_image чтобы "увидеть" интерфейс
    - execute_system_command может выполнить ЛЮБУЮ команду Windows/PowerShell
    - Можно создавать новые функции: click_by_coordinates, type_text, press_key, create_python_script

    Верни JSON с исправлением:
    {{
    "step": номер_шага,
    "description": "исправленное описание",
    "tool": "имя_инструмента", 
    "args": {{"параметры": "значения"}},
    "alternative_approach": "описание альтернативного подхода",
    "create_new_function": {{
        "name": "имя_новой_функции",
        "purpose": "для чего нужна",
        "implementation_hint": "как реализовать"
    }},
    "use_screenshots": true/false, # использовать ли скриншоты
    "use_commands": true/false, # использовать ли команды
    "fix_reason": "почему это исправление работает"
    }}

    Верни ТОЛЬКО JSON, без дополнительного текста."""

        try:
            response = call_ollama(fix_prompt, fast=True, options={"temperature": 0.2, "num_predict": 1024}, format="json")
            result = self._extract_json_from_text(response)
            
            if isinstance(result, dict):
                # Проверяем, что это действительно исправление
                if result.get("tool") and result.get("description"):
                    # Правило-ориентированное исправление для click_element
                    if tool_name == "click_element" and ("Unsupported token" in error_msg or "parsing css selector" in error_msg.lower()):
                        args = result.get("args", {})
                        # Если в args есть element_selector, заменяем на selector
                        if "element_selector" in args:
                            args["selector"] = args.pop("element_selector")
                        # Если selector - это словарь, извлекаем значение
                        if isinstance(args.get("selector"), dict):
                            selector_dict = args["selector"]
                            # Пытаемся извлечь значение из словаря
                            args["selector"] = selector_dict.get("element_selector") or selector_dict.get("selector") or selector_dict.get("element") or "a[href*='video']"
                        # Если selector все еще не строка, используем дефолтный
                        if not isinstance(args.get("selector"), str):
                            args["selector"] = "a[href*='/watch']"
                        result["args"] = args
                        logger.info(f"🔧 Применено правило-ориентированное исправление для click_element")
                                          
                    logger.info(f"✅ Получено исправление: {result.get('fix_reason', '')}")
                    return result
                

                
                # Добавить после существующих исправлений для click_element
                if tool_name == "click_element" and ("element not found" in error_msg.lower() or "селектор не найден" in error_msg.lower()):
                    logger.info("🔧 Пытаемся использовать click_at_coordinates как альтернативу")
                    # Делаем скриншот для анализа
                    screenshot_result = self.execute_tool({"name": "take_desktop_screenshot", "arguments": {"filename": "debug_coordinates.png"}})
                    if screenshot_result.get("status") == "success":
                        # Анализируем скриншот для поиска координат
                        analysis_prompt = f"Найди на скриншоте элемент '{step_desc}'. Укажи координаты X,Y для клика."
                        analysis_result = self.execute_tool({"name": "analyze_screen_region", "arguments": {
                            "x": 0, "y": 0, "width": 1920, "height": 1080, "question": analysis_prompt
                        }})
                        if analysis_result.get("status") == "success":
                            # Парсим координаты из анализа (это упрощенный пример)
                            # В реальности нужно добавить парсинг координат из текста анализа
                            return {
                                "step": failed_step.get("step", 1),
                                "description": f"{step_desc} (исправлено: клик по координатам)",
                                "tool": "click_at_coordinates",
                                "args": {"x": 500, "y": 300},  # Дефолтные координаты
                                "fix_reason": "Замена click_element на click_at_coordinates через анализ изображения"
                            }
                                
                
                
            elif isinstance(result, str):
                try:
                    result = json.loads(result)
                    if isinstance(result, dict) and result.get("tool"):
                        return result
                except:
                    pass
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при запросе исправления: {e}")
        
        # Если модель не смогла исправить, применяем правило-ориентированное исправление
        if tool_name == "click_element" and ("Unsupported token" in error_msg or "parsing css selector" in error_msg.lower()):
            logger.info("🔧 Применяю правило-ориентированное исправление для click_element")
            fixed_args = {}
            # Извлекаем селектор из оригинальных аргументов
            if isinstance(step_args, dict):
                selector = step_args.get("element_selector") or step_args.get("selector") or step_args.get("element")
                if isinstance(selector, dict):
                    selector = selector.get("element_selector") or selector.get("selector") or "a[href*='/watch']"
                if not isinstance(selector, str):
                    selector = "a[href*='/watch']"
                fixed_args["selector"] = selector
            else:
                fixed_args["selector"] = "a[href*='/watch']"
            
            return {
                "step": failed_step.get("step", 1),
                "description": step_desc + " (исправлено: используется правильный формат селектора)",
                "tool": "click_element",
                "args": fixed_args,
                "fix_reason": "Автоматическое исправление: селектор преобразован в строку"
            }
        
        return None

    def check_task_completion(self, original_task: str, executed_steps: List[Dict]) -> Tuple[bool, Optional[Dict]]:
        """Проверяет, завершена ли задача, и если нет - запрашивает следующий шаг у модели"""
        logger.info("🔍 Проверка завершенности задачи...")

        if self._detect_task_completion(original_task, executed_steps):
            logger.info("✅ Задача распознана как завершенная по выполненным шагам")
            return True, None
        
        # КРИТИЧЕСКОЕ ПРАВИЛО: После успешного открытия приложения переходим к GUI-автоматизации
        # Проверяем, было ли успешно открыто приложение
        app_opened = False
        for step in executed_steps:
            tool = step.get("tool") or step.get("name", "")
            status = step.get("status", "")
            if ("open_application" in tool or "locate_app_icon" in tool) and status == "success":
                app_opened = True
                app_name = (step.get("result", {}).get("application") or 
                           step.get("result", {}).get("path") or 
                           step.get("description", "")).lower()
                logger.info(f"✅ Приложение успешно открыто, переходим к GUI-автоматизации")
                break
        
        # Если приложение открыто и осталось выполнить задачу - берем скриншот и анализируем
        if app_opened and original_task:
            # Проверяем, еще ли нужно что-то делать
            task_lower = original_task.lower()
            
            # Если задача требует найти контакт или пользователя в открытом приложении
            if any(word in task_lower for word in ["найди", "найти", "поиск", "search", "find", "ищи"]):
                logger.info("📋 Задача требует поиска - переходим к анализу интерфейса через скриншот")
                return False, {
                    "step": len(executed_steps) + 1,
                    "description": "Анализ интерфейса приложения и поиск требуемого элемента",
                    "tool": "take_desktop_screenshot",
                    "args": {"filename": f"app_interface_{int(time.time())}.png"}
                }
            
            # Если задача требует отправить сообщение или выполнить действие
            if any(word in task_lower for word in ["напиши", "напишу", "отправь", "send", "write", "сообщение", "message"]):
                logger.info("📋 Задача требует действия в приложении - анализируем интерфейс")
                next_step = self._prepare_gui_analysis_step(
                    original_task,
                    executed_steps,
                    "Анализ интерфейса и определение координат для действия"
                )
                return False, next_step
        
        # КРИТИЧЕСКОЕ ПРАВИЛО #2: Если на предыдущем шаге была попытка открыть приложение,
        # а текущий шаг снова пытается открыть его - ПРОПУСКАЕМ и переходим к GUI-действиям
        if len(executed_steps) >= 2:
            last_step = executed_steps[-1]
            last_tool = (last_step.get("tool") or last_step.get("name", "")).lower()
            
            # Если последний шаг был неудачной попыткой запустить приложение через execute_system_command
            # и до этого было успешное открытие - игнорируем попытку и переходим к GUI
            if ("execute_system_command" in last_tool or "start" in str(last_step.get("result", {})).lower()) and \
               last_step.get("status") == "failed" and app_opened:
                logger.info("⚠️ ПРОПУСКАЕМ повторное открытие приложения — переходим к GUI-автоматизации")
                next_step = self._prepare_gui_analysis_step(
                    original_task,
                    executed_steps,
                    "Анализ интерфейса приложения для выполнения задачи"
                )
                return False, next_step
        
        # Формируем контекст выполненных шагов
        steps_summary = []
        for step in executed_steps:
            tool = step.get("tool") or step.get("name", "неизвестно")
            desc = step.get("description", "")
            status = step.get("status", "unknown")
            steps_summary.append(f"- {tool}: {desc} (статус: {status})")
        
        context = "\n".join(steps_summary)
        
        # Формируем список доступных инструментов
        tools_list = []
        for tool in self.tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            tools_list.append(f"- {name}: {desc}")
        tools_desc = "\n".join(tools_list[:20])  # Первые 20 инструментов
        # Запрещенные инструменты в текущей сессии
        frozen_list = ", ".join(sorted(list(self._frozen_tools))) if getattr(self, "_frozen_tools", None) else ""
        
        check_prompt = f"""Ты - AI-агент, который проверяет выполнение задачи.

ИСХОДНАЯ ЗАДАЧА: {original_task}

ВЫПОЛНЕННЫЕ ШАГИ:
{context}

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
{tools_desc}

ЗАПРЕЩЁННЫЕ (замороженные) ИНСТРУМЕНТЫ В ЭТОЙ СЕССИИ: {frozen_list}

ТВОЯ РАБОТА: 
1. Определи, полностью ли выполнена задача
2. Если задача НЕ завершена - определи следующий шаг для её выполнения

КРИТИЧЕСКИ ВАЖНОЕ ПРАВИЛО:
- ЕСЛИ приложение уже открыто (успешно выполнены шаги открытия) И осталось выполнить действия в приложении (поиск, ввод текста, клики):
  НЕ пытайся открывать приложение заново! Вместо этого:
  1. Сначала take_desktop_screenshot чтобы "увидеть" текущее состояние
  2. Затем analyze_image или analyze_screen_region чтобы найти нужные элементы
  3. Затем click_at_coordinates или type_text для выполнения действий

Верни JSON в формате:
{{
  "task_completed": true/false,
  "reason": "почему задача завершена или не завершена",
  "next_step": {{
    "step": номер_следующего_шага,
    "description": "описание следующего шага",
    "tool": "имя_инструмента",
    "args": {{"параметр": "значение"}}
  }}
}}

ВАЖНО: 
- Если задача требует нескольких действий (например, "открой камеру И сделай фото"), 
  и выполнено только первое действие - задача НЕ завершена. Думай как решить и по необходимости пиши новую функцию или выполняй необходимые команды или делай скриншоты и кликай мышкой по координатам.
- Если задача требует обработки множества элементов (например, "перейди по каждой ссылке из файла"), 
  и обработан не все элементы - задача НЕ завершена. Верни следующий шаг для следующего элемента.
- Используй только инструменты из списка выше
- Указывай точное имя инструмента (tool) из списка
- Для извлечения данных со страниц используй: скриншот + analyze_image или extract_text_from_page
- Для сохранения данных в таблицу используй write_csv_file

СТРОГИЙ ЗАПРЕТ: Не предлагай инструменты из списка ЗАПРЕЩЁННЫХ. Подбери альтернативу.

Верни ТОЛЬКО JSON, без дополнительного текста."""

        try:
            response = call_ollama(check_prompt, fast=True, options={"temperature": 0.2, "num_predict": 1024}, format="json")
            result = self._extract_json_from_text(response)
            
            if isinstance(result, dict):
                completed = result.get("task_completed", False)
                next_step = result.get("next_step")
                
                if completed:
                    logger.info(f"✅ Задача завершена: {result.get('reason', '')}")
                    return True, None
                elif next_step:
                    logger.info(f"⏭️ Задача не завершена: {result.get('reason', '')}")
                    logger.info(f"   Следующий шаг: {next_step.get('description', '')}")
                    return False, next_step
                else:
                    logger.warning("⚠️ Не удалось определить статус задачи")
                    return False, None
            else:
                logger.warning("⚠️ Неожиданный формат ответа при проверке завершенности")
                return False, None
        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки завершенности: {e}")
            return False, None

    def execute_plan(self, plan: List[Dict], stop_on_failure: bool = True, original_task: Optional[str] = None, iterative: bool = True) -> List[Dict]:
        """
        Выполняет план (список шагов).
        Каждый шаг может содержать:
         - "tool" или "name" - имя инструмента
         - "args" - dict аргументов
         - "wait_seconds" - опциональная пауза перед выполнением шага
        Если iterative=True, после выполнения каждого шага проверяет завершенность задачи
        и запрашивает следующий шаг у модели, если задача не завершена.
        Возвращает модифицированный план с полями "result" и "status".
        """
        logger.info("🚀 Запуск выполнения плана...")
        logger.info(f"📋 План содержит {len(plan)} шагов")
        if iterative:
            logger.info("🔄 Режим итеративного выполнения: после каждого шага будет проверяться завершенность задачи")
        
        # Определяем, нужно ли показывать браузер
        show_browser = self._should_show_browser(original_task or "")
        
        executed = []
        current_plan = plan.copy()
        max_iterations = 60  # Защита от бесконечного цикла (увеличен для полного выполнения GUI-действий: скрин + анализ + клик + тип + ввод + отправка)
        iteration = 0
        last_icon_coords: Optional[Tuple[int, int]] = None
        gui_automation_active = False  # Флаг для отслеживания режима GUI-автоматизации
        last_analyzed_coords: Optional[Tuple[int, int]] = None  # Последние найденные координаты из анализа
        prev_signature: Optional[str] = None
        repeat_fail_count: int = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # Выполняем шаги из текущего плана
            # Normalize current_plan to a list to satisfy iterability
            if current_plan is None:
                current_plan = []
            elif not isinstance(current_plan, list):
                current_plan = [current_plan]

            for idx, step in enumerate(current_plan):
                step_result = {"step": step.get("step", len(executed) + 1), "description": step.get("description", ""), "tool": step.get("tool") or step.get("name")}
                try:
                    # пауза, если указана
                    wait = step.get("wait_seconds") or step.get("delay_seconds") or step.get("delay") or 0
                    if wait:
                        logger.info(f"⏸ Ожидание {wait} секунд перед шагом {step_result['step']}")
                        time.sleep(float(wait))

                    tool_name = step.get("tool") or step.get("name")
                    args = step.get("args", {}) or {}
                    
                    # Исправляем headless для initialize_browser, если пользователь хочет видеть браузер
                    if tool_name == "initialize_browser" and show_browser:
                        if args.get("headless", False):
                            logger.info("🔧 Исправление: отключаем headless режим, так как пользователь хочет видеть браузер")
                            args["headless"] = False
                            step["args"] = args
                            # Пытаемся использовать открытый браузер даже без явной фразы
                            if self._should_use_existing_browser(original_task or ""):
                                args["use_existing"] = True
                                step["args"] = args
                    
                    # Логируем выбор инструмента моделью
                    if tool_name:
                        logger.info(f"🔧 Шаг {step_result['step']}: Модель выбрала инструмент '{tool_name}'")
                        logger.info(f"   Описание: {step_result['description']}")
                        if args:
                            logger.debug(f"   Аргументы: {args}")

                    # Если инструмент заморожен — пропускаем его и просим альтернативный шаг
                    if tool_name in self._frozen_tools:
                        logger.info(f"🧊 Инструмент '{tool_name}' заморожен для этой сессии, пропускаем шаг и запрашиваем альтернативу")
                        step_result["status"] = "skipped"
                        step_result["result"] = {"status": "skipped", "error": None}
                        executed.append(step_result)
                        if iterative and original_task:
                            completed, next_step = self.check_task_completion(original_task, executed)
                            if completed:
                                logger.info("✅ Задача полностью выполнена (после пропуска замороженного инструмента)!")
                                return executed
                            elif next_step:
                                current_plan = [next_step]
                                break
                        # Если нет следующего шага — просто продолжаем к следующему элементу плана
                        continue
                    # Предобработка URL плейсхолдеров для навигации
                    if tool_name == "navigate_to_url" and isinstance(args, dict):
                        try:
                            raw_url = args.get("url")
                            if isinstance(raw_url, str):
                                import re
                                text = raw_url
                                # Если строка начинается с http(s):// но далее содержит плейсхолдер — оставим только плейсхолдерную часть
                                if "Ссылка из" in text:
                                    # вырезаем часть после 'Ссылка из'
                                    m_cut = re.search(r"[Сс]сылка\s+из[\s:]+(.+)$", text)
                                    if m_cut:
                                        text = m_cut.group(0)
                                # Обработка формата: "Следующая ссылка из файла C:\path\links.txt"
                                if ("Ссылка из файла" in text) or ("Следующая ссылка из файла" in text):
                                    import re
                                    # Определяем режим и извлекаем путь
                                    m_next = re.search(r"[Сс]ледующая\s+ссылка\s+из\s+файла\s+([A-Za-z]:\\[^)\n]+)", raw_url)
                                    m_first = re.search(r"[Сс]сылка\s+из\s+файла\s+([A-Za-z]:\\[^)\n]+)", raw_url)
                                    file_path = None
                                    mode_next = False
                                    if m_next:
                                        file_path = m_next.group(1)
                                        mode_next = True
                                    elif m_first:
                                        file_path = m_first.group(1)
                                    if file_path:
                                        rf = self.fs_manager.read_file(file_path)
                                        content = rf.get("content") if isinstance(rf, dict) else rf
                                        lines: List[str] = []
                                        if isinstance(content, str):
                                            lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                                        elif isinstance(content, list):
                                            lines = [str(x).strip() for x in content if str(x).strip()]
                                        # Вычисляем индекс
                                        current_idx = self._url_iters.get(file_path, -1)
                                        new_idx = (current_idx + 1) if mode_next else 0
                                        if new_idx < 0:
                                            new_idx = 0
                                        if new_idx >= len(lines):
                                            logger.warning(f"⚠️ Нет {'следующей ' if mode_next else ''}ссылки в файле: {file_path}")
                                        else:
                                            selected_url = lines[new_idx]
                                            args["url"] = selected_url
                                            self._url_iters[file_path] = new_idx
                                            logger.info(f"📄 Разрешён URL из файла [{new_idx+1}/{len(lines)}]: {selected_url}")
                                # Обработка упрощенного формата: "Ссылка из links.txt" или "Следующая ссылка из links.txt"
                                else:
                                    m_next2 = re.search(r"[Сс]ледующая\s+ссылка\s+из\s+([^\n]+\.txt)", text)
                                    m_first2 = re.search(r"[Сс]сылка\s+из\s+([^\n]+\.txt)", text)
                                    file_name = None
                                    mode_next2 = False
                                    if m_next2:
                                        file_name = m_next2.group(1).strip().strip('"')
                                        mode_next2 = True
                                    elif m_first2:
                                        file_name = m_first2.group(1).strip().strip('"')
                                    if file_name:
                                        from pathlib import Path as _P
                                        candidates = []
                                        try:
                                            candidates.append(str(_P.cwd() / file_name))
                                        except Exception:
                                            pass
                                        try:
                                            candidates.append(str(_P(config.DOCUMENTS_DIR) / file_name))
                                        except Exception:
                                            pass
                                        try:
                                            candidates.append(str(_P(__file__).parent / file_name))
                                        except Exception:
                                            pass
                                        found_path = None
                                        for fp in candidates:
                                            try:
                                                rf = self.fs_manager.get_file_info(fp)
                                                if isinstance(rf, dict) and rf.get("status") == "success":
                                                    found_path = fp
                                                    break
                                            except Exception:
                                                continue
                                        if found_path:
                                            rf = self.fs_manager.read_file(found_path)
                                            content = rf.get("content") if isinstance(rf, dict) else rf
                                            lines: List[str] = []
                                            if isinstance(content, str):
                                                lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                                            elif isinstance(content, list):
                                                lines = [str(x).strip() for x in content if str(x).strip()]
                                            current_idx = self._url_iters.get(found_path, -1)
                                            new_idx = (current_idx + 1) if mode_next2 else 0
                                            if new_idx < 0:
                                                new_idx = 0
                                            if new_idx >= len(lines):
                                                logger.warning(f"⚠️ Нет {'следующей ' if mode_next2 else ''}ссылки в файле: {found_path}")
                                            else:
                                                selected_url = lines[new_idx]
                                                args["url"] = selected_url
                                                self._url_iters[found_path] = new_idx
                                                logger.info(f"📄 Разрешён URL из файла [{new_idx+1}/{len(lines)}]: {selected_url}")
                        except Exception as _e:
                            logger.debug(f"🔧 Не удалось предобработать URL из файла: {_e}")

                    args = self._refine_step_args_with_model(tool_name, args, step_result["description"]) if tool_name else args

# ... (rest of the code remains the same)
                    if not tool_name:
                        raise ValueError("Инструмент шага не указан")

                    # Специальная обработка вопросов для анализа изображений/экрана
                    if tool_name in {"analyze_image", "analyze_screen_region"} and isinstance(args, dict):
                        question_key = "question"
                        question = args.get(question_key)
                        if question:
                            action_hint = self._infer_action_from_description(step_result.get("description", ""))
                            args[question_key] = self._format_coordinate_question(question, action_hint)
                            step["args"] = args

                    # Формат для execute_tool
                    tool_call = {"name": tool_name, "arguments": args}

                    # Специальная обработка динамической последовательности шагов, возвращённой как dynamic_solution
                    if tool_name == "dynamic_sequence" and isinstance(args, dict) and isinstance(args.get("sequence"), list):
                        seq = args.get("sequence")
                        # нормализуем шаги: если шагы — это dict'ы, используем их как current_plan
                        logger.info("🔄 Применение динамической последовательности шагов (fallback)")
                        # Устанавливаем текущий план на последовательность шагов и прерываем цикл выполнения текущего плана
                        current_plan = seq
                        break

                    logger.info(f"⚙️ Выполнение инструмента '{tool_name}' (определено моделью)")
                    result = self.execute_tool(tool_call)

                    step_result["result"] = result
                    # Определяем статус шага: считаем шаг провальным если:
                    # - функция вернула dict с ключом 'error'
                    # - или вернула dict со статусом 'error'/'failed'
                    # - или вернула None/пустой результат
                    failed = False
                    if result is None:
                        failed = True
                    elif isinstance(result, dict):
                        if result.get("error"):
                            failed = True
                        else:
                            st = str(result.get("status") or "").lower()
                            if st in ("error", "failed"):
                                failed = True
                            # Явно считаем неуспехом для открытия приложения, если код возврата не 0
                            if tool_name in ("open_application", "open_application_advanced"):
                                try:
                                    rc = result.get("returncode")
                                    if rc is not None and int(rc) != 0:
                                        failed = True
                                except Exception:
                                    pass
                    step_result["status"] = "failed" if failed else "success"

                    # Stall detector: одинаковый шаг подряд и он падает → ускоренное динамическое решение
                    try:
                        sig = f"{tool_name}|{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
                    except Exception:
                        sig = f"{tool_name}|{str(args)}"
                    if step_result["status"] == "failed":
                        if prev_signature == sig:
                            repeat_fail_count += 1
                        else:
                            repeat_fail_count = 1
                        prev_signature = sig
                        if repeat_fail_count >= 2 and iterative and original_task:
                            if tool_name not in self._frozen_tools:
                                self._frozen_tools.add(tool_name)
                                logger.info(f"🧊 Инструмент '{tool_name}' заморожен из-за повторных провалов одного и того же шага")
                            dynamic_solution = self._handle_repeated_failure(original_task, step_result, executed)
                            if dynamic_solution:
                                logger.info("🎯 Срабатывание ускоренного динамического решения после повторных провалов")
                                current_plan = [dynamic_solution]
                                executed.append(step_result)
                                break
                    else:
                        prev_signature = None
                        repeat_fail_count = 0

                    if step_result["status"] == "success":
                        self._post_verify_ui_step(tool_name, args, step_result)
                    self._reset_failed_attempts(step_result["description"], tool_name)
                    logger.info(f"🔹 Шаг {step_result['step']} ({tool_name}) выполнен: {step_result['status']}")

                    executed.append(step_result)

                    if original_task and self._detect_task_completion(original_task, executed):
                        logger.info("🎯 Задача уже выполнена согласно последним шагам — завершаем план")
                        return executed

                    # Сохраняем координаты ярлыка для последующего клика
                    if tool_name == "locate_app_icon_on_desktop" and isinstance(result, dict) and result.get("status") == "success":
                        try:
                            x_raw = result.get("x")
                            y_raw = result.get("y")
                            # Явно проверяем на None перед приведением в int — это устраняет предупреждения типизации
                            if x_raw is None or y_raw is None:
                                raise ValueError("missing coordinates")
                            x = int(x_raw)
                            y = int(y_raw)
                            last_icon_coords = (x, y)
                        except Exception:
                            last_icon_coords = None
                    
                    # ✅ НОВОЕ: Парсим координаты из analyze_screen_region и считаем отсутствие координат ошибкой
                    if tool_name in ("analyze_screen_region", "analyze_image") and isinstance(result, dict):
                        requires_coords = COORDINATE_PROMPT_MARKER in str((step.get("args") or {}).get("question", ""))
                        parsed_ok, parsed_coords, raw_text = self._extract_coordinate_analysis(result)
                        step_result.setdefault("analysis", {})
                        step_result["analysis"].update({
                            "ok": parsed_ok,
                            "coordinates": parsed_coords,
                            "raw": raw_text
                        })
                        if parsed_ok and parsed_coords:
                            first = parsed_coords[0]
                            try:
                                last_analyzed_coords = (int(first.get("x")), int(first.get("y")))
                                logger.info(f"📍 Найдены координаты из анализа JSON: {last_analyzed_coords}")
                            except Exception:
                                last_analyzed_coords = None
                        elif requires_coords and step_result.get("status") == "success":
                            logger.warning("⚠️ Анализ экрана не вернул координаты, помечаем шаг как неудачный")
                            step_result["status"] = "failed"
                            step_result.setdefault("result", {})
                            step_result["result"]["error"] = "vision_no_coordinates"

                    # Если locate_app_icon_on_desktop вернул частичный результат (координаты не извлечены) —
                    # автоматически пробуем найти exe/ярлык и запустить приложение как fallback.
                    if tool_name == "locate_app_icon_on_desktop" and isinstance(result, dict):
                        stat = str(result.get("status") or "").lower()
                        coords_missing = not (result.get("x") is not None and result.get("y") is not None)
                        if stat == "partial" or coords_missing:
                            app_name = (args or {}).get("app_name")
                            if app_name:
                                logger.info(f"🔄 Фолбэк: координаты не найдены, пытаемся запустить '{app_name}' через open_application_advanced")
                                try:
                                    open_res = self.execute_tool({"name": "open_application_advanced", "arguments": {"app_name": app_name}})
                                except Exception as e:
                                    open_res = {"error": str(e)}

                                # Оцениваем результат открытия
                                opened_failed = False
                                if open_res is None:
                                    opened_failed = True
                                elif isinstance(open_res, dict):
                                    if open_res.get("error"):
                                        opened_failed = True
                                    elif str(open_res.get("status") or "").lower() in ("error", "failed"):
                                        opened_failed = True

                                synth = {
                                    "step": step_result.get("step", 1) + 1,
                                    "description": f"Фолбэк: запуск {app_name} через open_application_advanced",
                                    "tool": "open_application_advanced",
                                    "result": open_res,
                                    "status": "failed" if opened_failed else "success"
                                }
                                logger.info(f"🔹 Фолбэк-результат: {synth['status']}")
                                executed.append(synth)
                                # Если удалось открыть — проверяем завершенность и продолжаем
                                if synth["status"] == "success" and iterative and original_task:
                                    completed, next_step = self.check_task_completion(original_task, executed)
                                    if completed:
                                        logger.info("✅ Задача полностью выполнена (фолбэк)!")
                                        return executed
                                    elif next_step:
                                        current_plan = [next_step]
                                        break
                    # Если план предполагает клик по координатам, а ранее были извлечены координаты — применяем их
                    if tool_name == "click_at_coordinates":
                        step_args = step.setdefault("args", {}) if isinstance(step.get("args"), dict) else {}
                        # Приоритет 1: координаты из анализа экрана
                        if last_analyzed_coords and last_analyzed_coords[0] > 0 and last_analyzed_coords[1] > 0:
                            logger.info(f"📍 Используем координаты из анализа: {last_analyzed_coords}")
                            step_args["x"], step_args["y"] = last_analyzed_coords
                            last_analyzed_coords = None  # Сброс после применения
                            # ВАЖНО: синхронизируем локальную переменную args для текущего вызова инструмента
                            args = step_args
                        # Приоритет 2: координаты найденного ярлыка/иконки
                        elif last_icon_coords and last_icon_coords[0] > 0 and last_icon_coords[1] > 0:
                            step_args.setdefault("x", last_icon_coords[0])
                            step_args.setdefault("y", last_icon_coords[1])
                            args = step_args

                    # Если итеративный режим и шаг успешен - проверяем завершенность задачи
                    if iterative and step_result["status"] == "success" and original_task:
                        # КРИТИЧЕСКОЕ ДОБАВЛЕНИЕ: Если был скриншот и задача требует GUI-действий - анализируем и определяем координаты
                        # НО только в первый раз (при первом переходе в режим GUI-автоматизации)
                        if tool_name == "take_desktop_screenshot" and not gui_automation_active:
                            screenshot_path = step_result.get("result", {}).get("file_path")
                            if screenshot_path:
                                logger.info(f"📸 Скриншот успешно создан, анализируем интерфейс для автоматизации")
                                # Используем вспомогательный метод для построения GUI-потока
                                active_app_name = None
                                try:
                                    aw = self.execute_tool({"name": "get_active_window_info", "arguments": {}})
                                    if isinstance(aw, dict):
                                        active_app_name = aw.get("process_name") or aw.get("title")
                                except Exception:
                                    active_app_name = None
                                if not active_app_name:
                                    # Пытаемся извлечь из исходной задачи
                                    try:
                                        import re as _re
                                        m_app = _re.search(r"telegram|whatsapp|skype|notepad|excel|word|chrome|edge|firefox", (original_task or ""), _re.IGNORECASE)
                                        if m_app:
                                            active_app_name = m_app.group(0)
                                    except Exception:
                                        active_app_name = None
                                gui_steps = self._build_gui_automation_flow(active_app_name or "приложение", original_task, screenshot_path)
                                if gui_steps:
                                    logger.info(f"🔨 Применяем построенный GUI-поток ({len(gui_steps)} шагов)")
                                    gui_automation_active = True  # Включаем режим GUI-автоматизации
                                    current_plan = gui_steps
                                    break
                        
                        # 🔥 ИСПРАВЛЕНИЕ: Не вызываем check_task_completion если уже в режиме GUI-автоматизации
                        # Дождёмся пока все GUI-шаги выполнятся
                        if not gui_automation_active:
                            completed, next_step = self.check_task_completion(original_task, executed)
                            if completed:
                                logger.info("✅ Задача полностью выполнена!")
                                return executed
                            elif next_step:
                                logger.info(f"🔄 Добавляем следующий шаг в план: {next_step.get('description', '')}")
                                # Добавляем следующий шаг в план
                                current_plan = [next_step]
                                break  # Выходим из цикла for, чтобы начать новую итерацию while
                            # Если next_step None, продолжаем выполнение текущего плана
                        else:
                            # Если в режиме GUI-автоматизации и это финальный скриншот - проверяем завершенность
                            if tool_name == "take_desktop_screenshot":
                                completed, next_step = self.check_task_completion(original_task, executed)
                                if completed:
                                    logger.info("✅ Задача полностью выполнена (после GUI-автоматизации)!")
                                    return executed

                    # Если шаг провалился - анализируем ошибку и предлагаем исправление
                    if step_result["status"] == "failed" and iterative and original_task:
                        error_msg = str(step_result.get("result", {}).get("error", ""))
                        logger.warning(f"⚠️ Шаг провалился, анализируем ошибку: {error_msg[:100]}")

                        # Специальный фолбэк для navigate_to_url с использованием существующего браузера через GUI
                        if tool_name == "navigate_to_url" and self._should_use_existing_browser(original_task or ""):
                            url_val = (args or {}).get("url")
                            if url_val:
                                logger.info("🔄 Фолбэк: ввод URL через горячие клавиши в существующем браузере")
                                try:
                                    self.execute_tool({"name": "press_hotkey", "arguments": {"keys": ["ctrl", "l"]}})
                                    self.execute_tool({"name": "type_text", "arguments": {"text": str(url_val)}})
                                    self.execute_tool({"name": "press_key", "arguments": {"key": "enter"}})
                                    # Добавим краткую паузу
                                    self.execute_tool({"name": "wait_for_seconds", "arguments": {"seconds": 2}})
                                except Exception:
                                    pass
                        
                        # Увеличиваем счетчик неудач
                        self._increment_failed_attempts(step_result["description"], tool_name)

                        # Немедленный целевой фолбэк для открытия приложений (первая неудача)
                        if tool_name == "open_application" and self._count_failed_attempts(step_result["description"], tool_name) == 1:
                            app_arg = (step.get("args") or {}).get("app_name") or "Telegram"
                            logger.info("🔄 Фолбэк: пробуем find_executable + open_application_advanced")
                            try:
                                find_res = self.execute_tool({"name": "find_executable", "arguments": {"app_name": app_arg}})
                            except Exception as e:
                                find_res = {"error": str(e)}
                            executed.append({
                                "step": step_result.get("step", 1) + 0.1,
                                "description": f"Найти путь к исполняемому файлу для {app_arg}",
                                "tool": "find_executable",
                                "result": find_res,
                                "status": ("failed" if isinstance(find_res, dict) and (find_res.get("error") or str(find_res.get("status", "")).lower() in ("error", "failed")) else "success")
                            })
                            try:
                                open_res = self.execute_tool({"name": "open_application_advanced", "arguments": {"app_name": app_arg}})
                            except Exception as e:
                                open_res = {"error": str(e)}
                            executed.append({
                                "step": step_result.get("step", 1) + 0.2,
                                "description": f"Запуск {app_arg} по найденному пути",
                                "tool": "open_application_advanced",
                                "result": open_res,
                                "status": ("failed" if isinstance(open_res, dict) and (open_res.get("error") or str(open_res.get("status", "")).lower() in ("error", "failed")) else "success")
                            })
                            # После целевого фолбэка сразу проверим завершенность
                            completed, next_step = self.check_task_completion(original_task, executed)
                            if completed:
                                logger.info("✅ Задача полностью выполнена (после фолбэк открытия приложения)!")
                                return executed
                            elif next_step:
                                current_plan = [next_step]
                                break

                        # Если инструмент для этого шага уже неудачно пробовался 2+ раза — заморозить
                        if self._count_failed_attempts(step_result["description"], tool_name) >= 2:
                            if tool_name not in self._frozen_tools:
                                self._frozen_tools.add(tool_name)
                                logger.info(f"🧊 Инструмент '{tool_name}' заморожен для текущей сессии после повторных неудач")
                        
                        # 🔥 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: передаем executed вместо executed_steps
                        # Проверяем, не превышен ли лимит неудач (более трёх раз)
                        dynamic_solution = self._handle_repeated_failure(original_task, step_result, executed)
                        if dynamic_solution:
                            logger.info(f"🎯 Применяем динамическое решение после многократных неудач: {dynamic_solution.get('description', '')}")
                            current_plan = [dynamic_solution]
                            break
                        
                        # 🔥 ДОБАВЛЯЕМ: Проверяем количество неудачных попыток перед обычным исправлением
                        failed_count = self._count_failed_attempts(step_result["description"], tool_name)
                        if failed_count < 3:
                            # Пытаемся исправить шаг (только если меньше 3 неудач)
                            fixed_step = self._fix_failed_step(original_task, step_result, executed)
                            if fixed_step:
                                # Проверяем, что исправление отличается
                                if (fixed_step.get("tool") != step_result.get("tool") or 
                                    fixed_step.get("description") != step_result.get("description") or
                                    fixed_step.get("args") != step_result.get("args")):
                                    logger.info(f"🔧 Получено исправление (попытка {failed_count}/3): {fixed_step.get('description', '')}")
                                    current_plan = [fixed_step]
                                    break
                                else:
                                    logger.warning(f"⚠️ Исправление идентично провалившемуся шагу, продолжаем... (попытка {failed_count}/3)")
                        else:
                            logger.warning(f"🚨 Достигнут лимит неудачных попыток ({failed_count}) для этого шага. Ждем динамического решения.")

                    if step_result["status"] == "failed" and stop_on_failure:
                        try:
                            er_tmpl = self.prompts.get("error_recovery", {}).get("template")
                            if er_tmpl:
                                er_prompt = er_tmpl.format(tool_name=tool_name or "", error_message=str(step_result.get("result", {})), original_task=original_task or step_result["description"])
                                er_resp = call_ollama(er_prompt, fast=True, options={"num_ctx": 1024, "num_predict": 128}, format="json")
                                new_plan = self._extract_json_from_text(er_resp)
                                if isinstance(new_plan, list) and new_plan:
                                    rec_exec = self.execute_plan(new_plan, stop_on_failure=True, original_task=original_task or step_result["description"], iterative=False)
                                    executed.extend(rec_exec)
                                    break
                        except Exception:
                            pass
                        break
                except Exception as e:
                    logger.error(f"❌ Ошибка выполнения шага {step_result.get('step')}: {e}")
                    step_result["result"] = {"error": str(e)}
                    step_result["status"] = "failed"
                    executed.append(step_result)
                    if stop_on_failure:
                        break
            
            # Если выполнили все шаги из плана и не в итеративном режиме - выходим
            if not iterative or not original_task:
                break
            
            # Если в итеративном режиме и выполнили все шаги - проверяем завершенность
            # Ensure we don't call len() on a non-list; treat non-list as empty
            if iterative and original_task and (not isinstance(current_plan, list) or len(current_plan) == 0):
                completed, next_step = self.check_task_completion(original_task, executed)
                if completed:
                    logger.info("✅ Задача полностью выполнена!")
                    break
                elif next_step:
                    logger.info(f"🔄 Добавляем следующий шаг в план: {next_step.get('description', '')}")
                    current_plan = [next_step]
                else:
                    logger.info("⚠️ Не удалось определить следующий шаг, запрашиваем у модели один следующий шаг")
                    dyn_next = self._ask_model_next_step(original_task, executed)
                    if isinstance(dyn_next, dict) and dyn_next.get("tool"):
                        logger.info(f"🧭 Модель предложила следующий шаг: {dyn_next.get('description','')}")
                        current_plan = [dyn_next]
                    else:
                        logger.info("⚠️ Модель не предложила следующий шаг, завершаем выполнение")
                        break
                    break

        if iteration >= max_iterations:
            logger.warning(f"⚠️ Достигнут лимит итераций ({max_iterations}), завершаем выполнение")

        return executed

    def _extract_url_or_domain(self, text: str) -> Optional[str]:
        try:
            rx = re.compile(config.PATTERNS.get("url", r"https?://[^\s]+"), re.IGNORECASE)
            m = rx.search(text)
            if m:
                return m.group(0)
            dom = None
            for token in ["avito.ru", "yandex.ru", "google.com", "bing.com"]:
                if token in text.lower():
                    dom = token
                    break
            if dom:
                if not dom.startswith("http"):
                    return f"https://{dom}"
            return None
        except Exception:
            return None

    def _find_ui_element_coordinates(self, screenshot_path: str, element_type: str, task_context: str = "") -> Optional[Tuple[int, int]]:
        """
        Ищет координаты UI элемента на скриншоте с помощью LLM анализа.
        Поддерживает fallback на типичные координаты если анализ не сработал.
        
        Args:
            screenshot_path: путь к скриншоту
            element_type: тип элемента ("search_field", "input_field", "send_button", "contact", etc)
            task_context: контекст задачи для лучшего анализа
        
        Returns:
            Кортеж (x, y) или None если не найдено
        """
        try:
            from run_check_model import analyze_image
            
            # Формируем вопрос для анализа
            questions = {
                "search_field": f"Найди и укажи координаты X,Y центра поля для поиска или поля ввода {task_context}. Возвращай только два числа через запятую: X,Y",
                "input_field": f"Найди и укажи координаты X,Y центра поля для ввода текста {task_context}. Возвращай только два числа через запятую: X,Y",
                "send_button": "Найди и укажи координаты X,Y центра кнопки отправки или кнопки с символом стрелки. Возвращай только два числа через запятую: X,Y",
                "contact": "Найди координаты X,Y центра первого контакта или результата поиска в списке. Возвращай только два числа через запятую: X,Y",
                "chat_input": "Найди координаты X,Y центра поля ввода сообщения в чате. Возвращай только два числа через запятую: X,Y"
            }
            
            question = questions.get(element_type, "Найди координаты нужного элемента. Возвращай: X,Y")
            
            logger.info(f"🔍 Анализируем скриншот для поиска '{element_type}'")
            result = analyze_image(screenshot_path, question)
            
            if result.get("error"):
                logger.warning(f"⚠️ Ошибка анализа: {result['error']}")
                return None
            
            analysis = result.get("analysis", "").strip()
            if not analysis:
                logger.warning(f"⚠️ Анализ вернул пустой результат для '{element_type}'")
                return None
            
            # Пытаемся извлечь координаты из анализа
            import re
            # Ищем паттерны типа "123,456" или "X=123 Y=456"
            coord_patterns = [
                r'(\d+)\s*,\s*(\d+)',  # "123,456"
                r'[Xx]\s*[=:]\s*(\d+)[,\s]+[Yy]\s*[=:]\s*(\d+)',  # "X=123 Y=456"
                r'координ[^:]*:\s*(\d+)[,\s]+(\d+)',  # "координаты: 123, 456"
            ]
            
            # Определяем актуальное разрешение экрана для валидации
            sw, sh = self._get_screen_resolution()

            for pattern in coord_patterns:
                match = re.search(pattern, analysis)
                if match:
                    try:
                        x, y = int(match.group(1)), int(match.group(2))
                        # Проверяем что координаты в разумных пределах (динамическое разрешение экрана)
                        if 0 <= x <= sw and 0 <= y <= sh:
                            logger.info(f"✅ Найдены координаты '{element_type}': ({x}, {y})")
                            return (x, y)
                    except (ValueError, AttributeError):
                        continue
            
            logger.warning(f"⚠️ Не удалось извлечь координаты из анализа: {analysis[:100]}")
            return None
            
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при анализе элемента: {e}")
            return None

    def _get_fallback_coordinates(self, element_type: str, screen_width: int = 1920, screen_height: int = 1080) -> Tuple[int, int]:
        """
        Возвращает типовые/fallback координаты для стандартных элементов UI.
        Используется если LLM анализ не сработал или вернул пустой результат.
        """
        # Универсальные эвристики для типичных десктопных UI (без привязки к конкретному приложению)
        fallback_coords = {
            "search_field": (screen_width // 2, max(40, int(0.05 * screen_height))),  # верхняя полоса по центру
            "input_field": (screen_width // 2, max(40, int(0.05 * screen_height))),   # верхняя полоса по центру
            "send_button": (screen_width - int(0.06 * screen_width), screen_height - int(0.09 * screen_height)),  # правая нижняя зона
            "contact": (int(0.12 * screen_width), int(0.28 * screen_height)),  # левая колонка, середина
            "chat_input": (screen_width - int(0.1 * screen_width), screen_height - int(0.055 * screen_height)),  # правая нижняя зона ввода
        }
        
        coords = fallback_coords.get(element_type, (screen_width // 2, screen_height // 2))
        logger.info(f"📍 Используем fallback координаты для '{element_type}': {coords}")
        return coords

    def _get_screen_resolution(self) -> Tuple[int, int]:
        """Возвращает текущее разрешение экрана (ширина, высота). Фолбэк: 1920x1080."""
        try:
            if pyautogui is not None:
                size = pyautogui.size()
                if size and getattr(size, 'width', None) and getattr(size, 'height', None):
                    return int(size.width), int(size.height)
        except Exception as e:
            logger.debug(f"Не удалось получить разрешение экрана через pyautogui: {e}")
        # Фолбэк
        return 1920, 1080

    def _clamp_region(self, x: int, y: int, width: int, height: int) -> Tuple[int, int, int, int]:
        """Ограничивает регион анализируемой области в пределах активного окна (если доступно) или экрана."""
        rect = self._get_active_window_rect()  # (x,y,w,h) или None
        if rect and all(isinstance(v, (int, float)) for v in rect):
            ax, ay, aw, ah = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
            x2 = max(ax, min(ax + aw - 1, x))
            y2 = max(ay, min(ay + ah - 1, y))
            w2 = max(1, min(width, ax + aw - x2))
            h2 = max(1, min(height, ay + ah - y2))
            return x2, y2, w2, h2
        # Фолбэк: весь экран
        sw, sh = self._get_screen_resolution()
        x2 = max(0, min(x, sw - 1))
        y2 = max(0, min(y, sh - 1))
        w2 = max(1, min(width, sw - x2))
        h2 = max(1, min(height, sh - y2))
        return x2, y2, w2, h2

    def _get_active_window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """Возвращает прямоугольник активного окна (x, y, width, height) через PowerShell+user32. Фолбэк: None."""
        try:
            ps = r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
}
public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
"@
$hwnd = [Win32]::GetForegroundWindow()
if ($hwnd -eq [IntPtr]::Zero) { exit 1 }
$r = New-Object RECT
[Win32]::GetWindowRect($hwnd, [ref]$r) | Out-Null
$w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
Write-Output "$($r.Left),$($r.Top),$w,$h"
"""
            cmd = {"command": f"powershell -NoProfile -Command \"{ps}\""}
            res = self.command_manager.execute_system_command(**cmd)
            if isinstance(res, dict) and str(res.get("status", "")).lower() == "success":
                out = str(res.get("stdout", "")).strip()
                m = re.search(r"(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)", out)
                if m:
                    x, y, w, h = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    if w > 0 and h > 0:
                        return (x, y, w, h)
        except Exception:
            return None
        return None

    def _build_gui_automation_flow(self, app_name: str, task: str, screenshot_path: str) -> List[Dict[str, Any]]:
        """
        Строит поток GUI-автоматизации для приложения на основе анализа скриншота.
        Использует ГИБРИДНЫЙ подход:
        1. Сначала пытается использовать LLM анализ скриншота для определения координат
        2. Если анализ не сработал - использует fallback координаты
        3. Для каждого действия предварительно ищет правильные координаты
        
        Это делает агента универсальным для ЛЮБЫХ приложений, а не только Telegram.
        """
        logger.info(f"🔨 Построение потока GUI-автоматизации для {app_name}")
        
        steps: List[Dict[str, Any]] = []
        task_lower = task.lower()
        step_counter = 1
        screen_w, screen_h = self._get_screen_resolution()
        # Если доступен прямоугольник активного окна — используем его для глобальных анализов
        aw_rect = self._get_active_window_rect()
        if aw_rect and all(isinstance(v, (int, float)) for v in aw_rect):
            aw_x, aw_y, aw_w, aw_h = int(aw_rect[0]), int(aw_rect[1]), int(aw_rect[2]), int(aw_rect[3])
        else:
            aw_x, aw_y, aw_w, aw_h = 0, 0, screen_w, screen_h
        
        # Шаг 0: Сфокусировать и (опционально) развернуть окно приложения
        try:
            app_proc_name = str(app_name).split()[0]
        except Exception:
            app_proc_name = str(app_name)
        steps.append({
            "step": step_counter,
            "description": f"Фокус и разворачивание окна приложения {app_name}",
            "tool": "focus_window",
            "args": {"app_name": app_proc_name, "maximize": True}
        })
        step_counter += 1

        # Извлекаем поисковый запрос и текст сообщения из задачи
        import re
        search_query = None
        message_text = None
        contact_name = None

        # 1) Попытка: точечные шаблоны на исходном тексте (с сохранением регистра)
        # Найти имя пользователя/контакта в кавычках после глаголов "найди|найти|ищи|поиск"
        m_contact = re.search(r"(?:найди|найти|ищи|поиск)[^'\"]{0,80}['\"]([^'\"]+)['\"]", task, flags=re.IGNORECASE)
        if m_contact:
            contact_name = m_contact.group(1).strip()
            search_query = contact_name

        # 2) Попытка: если не нашли контакт, берем первое кавычечное выражение как имя
        if not contact_name:
            m_first_quote = re.findall(r"['\"]([^'\"]+)['\"]", task)
            if m_first_quote:
                # Если в запросе два кавычечных фрагмента, обычно 1-й — контакт, 2-й — сообщение
                contact_name = m_first_quote[0].strip()
                search_query = contact_name
                if len(m_first_quote) >= 2 and not message_text:
                    message_text = m_first_quote[1].strip()

        # 3) Извлечь текст сообщения: после слов "напиши|отправь" возможно с "сообщение"
        if not message_text:
            m_msg = re.search(r"(?:напиши|отправь)(?:\s+ему|\s+ей|\s+им)?(?:\s+сообщение)?\s*['\"]([^'\"]+)['\"]", task, flags=re.IGNORECASE)
            if m_msg:
                message_text = m_msg.group(1).strip()

        # 4) Фолбэки: если имя/сообщение всё ещё не извлечены
        if not search_query:
            # из нижнего регистра по предыдущей логике
            m_contact_low = re.search(r"(?:найди|найти|ищи|поиск)[^'\"]{0,80}['\"]([^'\"]+)['\"]", task_lower, flags=re.IGNORECASE)
            if m_contact_low:
                search_query = m_contact_low.group(1).strip()
                contact_name = search_query
        if not message_text:
            # если есть вторая кавычечная группа
            quoted = re.findall(r"['\"]([^'\"]+)['\"]", task)
            if len(quoted) >= 2:
                message_text = quoted[1].strip()

        # 5) Последние дефолты на случай полного отсутствия
        if not search_query:
            search_query = contact_name or "Виталик"
            contact_name = search_query
        if not message_text:
            message_text = "Привет"
        
        # 🔍 ПОИСК
        if any(word in task_lower for word in ["найди", "найти", "ищи", "поиск"]):
            search_match = re.search(r'(найди|ищи|поиск|найти)\s+(?:пользователя\s+|контакт\s+)?[\""\']*([^\"\']+?)[\""\']*(?:\s+и\s+|$)', task_lower)
            if search_match:
                search_query = search_match.group(2).strip()
                contact_name = search_query
            
            logger.info(f"🔍 Поисковый запрос: '{search_query}'")
            
            # Шаг 1: Анализируем скриншот и ищем поле поиска
            search_coords = self._find_ui_element_coordinates(screenshot_path, "search_field", app_name)
            if not search_coords:
                search_coords = self._get_fallback_coordinates("search_field", screen_w, screen_h)
            
            steps.append({
                "step": step_counter,
                "description": f"Клик на поле поиска ({search_coords[0]}, {search_coords[1]})",
                "tool": "click_at_coordinates",
                "args": {
                    "x": search_coords[0],
                    "y": search_coords[1]
                }
            })
            step_counter += 1
            
            # Шаг 2: Небольшая пауза после клика
            steps.append({
                "step": step_counter,
                "description": "Пауза для активации поля",
                "tool": "wait_for_seconds",
                "args": {"seconds": 0.5}
            })
            step_counter += 1
            
            # Шаг 3: Ввод поискового запроса
            steps.append({
                "step": step_counter,
                "description": f"Ввод '{search_query}' в поле поиска",
                "tool": "type_text",
                "args": {"text": str(search_query)}
            })
            step_counter += 1
            
            # Шаг 4: Нажатие Enter для выполнения поиска
            steps.append({
                "step": step_counter,
                "description": "Нажатие Enter для выполнения поиска",
                "tool": "press_key",
                "args": {"key": "Return"}
            })
            step_counter += 1
            
            # Шаг 5: Ожидание загрузки результатов
            steps.append({
                "step": step_counter,
                "description": "Ожидание загрузки результатов поиска (2 сек)",
                "tool": "wait_for_seconds",
                "args": {"seconds": 2}
            })
            step_counter += 1
            
            # Шаг 6: Скриншот с результатами
            steps.append({
                "step": step_counter,
                "description": "Скриншот результатов поиска",
                "tool": "take_desktop_screenshot",
                "args": {"filename": f"search_results_{int(time.time())}.png"}
            })
            step_counter += 1
            
            # Шаг 7: Анализируем скриншот для поиска контакта в результатах
            steps.append({
                "step": step_counter,
                "description": f"Анализ результатов для поиска контакта '{contact_name}'",
                "tool": "analyze_screen_region",
                "args": {
                    "x": aw_x,
                    "y": aw_y,
                    "width": aw_w,
                    "height": aw_h,
                    "question": f"Найди в результатах поиска контакт '{contact_name}' и укажи координаты X,Y центра на контакт. Возвращай только: X,Y"
                }
            })
            step_counter += 1
            
            # Шаг 8: Клик на результат поиска (используем fallback если анализ не сработает)
            contact_coords = self._get_fallback_coordinates("contact", screen_w, screen_h)
            steps.append({
                "step": step_counter,
                "description": f"Клик на контакт '{contact_name}' ({contact_coords[0]}, {contact_coords[1]})",
                "tool": "click_at_coordinates",
                "args": {
                    "x": contact_coords[0],
                    "y": contact_coords[1]
                }
            })
            step_counter += 1
            
            # Шаг 9: Ожидание открытия чата
            steps.append({
                "step": step_counter,
                "description": "Ожидание открытия чата (1.5 сек)",
                "tool": "wait_for_seconds",
                "args": {"seconds": 1.5}
            })
            step_counter += 1
        
        # 💬 ОТПРАВКА СООБЩЕНИЯ
        if any(word in task_lower for word in ["напиши", "напишу", "отправь", "send", "сообщение", "message"]):
            # message_text уже пытаемся извлечь выше на исходном тексте; здесь только финальный фолбэк
            if not message_text:
                msg_match2 = re.search(r'(?:напиши|отправь|message|send|сообщение)\s+(?:ему|ей|им\s+)?(?:сообщение\s+)?["\"]([^"\']+)["\"]', task, flags=re.IGNORECASE)
                message_text = msg_match2.group(1).strip() if msg_match2 else "Привет"
            
            logger.info(f"💬 Текст сообщения: '{message_text}'")
            
            # Если был поиск - добавляем скриншот чата перед вводом
            if search_query and len(steps) > 0:
                steps.append({
                    "step": step_counter,
                    "description": "Скриншот открытого чата",
                    "tool": "take_desktop_screenshot",
                    "args": {"filename": f"chat_opened_{int(time.time())}.png"}
                })
                step_counter += 1
            
            # Шаг: Анализируем скриншот и ищем поле ввода сообщения
            steps.append({
                "step": step_counter,
                "description": "Анализ интерфейса для поиска поля ввода сообщения",
                "tool": "analyze_screen_region",
                "args": {
                    "x": aw_x,
                    "y": aw_y,
                    "width": aw_w,
                    "height": aw_h,
                    "question": f"Найди поле ввода сообщения в {app_name}. Укажи координаты X,Y центра поля. Возвращай только: X,Y"
                }
            })
            step_counter += 1
            
            # Шаг: Клик на поле ввода (с fallback координатами)
            input_coords = self._get_fallback_coordinates("chat_input", screen_w, screen_h)
            steps.append({
                "step": step_counter,
                "description": f"Клик на поле ввода сообщения ({input_coords[0]}, {input_coords[1]})",
                "tool": "click_at_coordinates",
                "args": {
                    "x": input_coords[0],
                    "y": input_coords[1]
                }
            })
            step_counter += 1
            
            # Шаг: Пауза для активации поля
            steps.append({
                "step": step_counter,
                "description": "Пауза для активации поля ввода",
                "tool": "wait_for_seconds",
                "args": {"seconds": 0.5}
            })
            step_counter += 1
            
            # Шаг: Ввод текста сообщения
            steps.append({
                "step": step_counter,
                "description": f"Ввод сообщения: '{message_text}'",
                "tool": "type_text",
                "args": {"text": message_text}
            })
            step_counter += 1
            
            # Шаг: Отправка сообщения (Enter)
            steps.append({
                "step": step_counter,
                "description": "Отправка сообщения (Enter)",
                "tool": "press_key",
                "args": {"key": "Return"}
            })
            step_counter += 1
            
            # Шаг: Ожидание отправки
            steps.append({
                "step": step_counter,
                "description": "Ожидание отправки сообщения (1.5 сек)",
                "tool": "wait_for_seconds",
                "args": {"seconds": 1.5}
            })
            step_counter += 1
            
            # Шаг: Финальный скриншот подтверждения
            steps.append({
                "step": step_counter,
                "description": "Финальный скриншот - подтверждение отправки",
                "tool": "take_desktop_screenshot",
                "args": {"filename": f"message_sent_{int(time.time())}.png"}
            })
        
        logger.info(f"✅ Построено {len(steps)} шагов GUI-автоматизации")
        return steps

    def _rule_based_plan(self, task_description: str) -> List[Dict]:
        """Создает правило-ориентированный план для простых задач"""
        td = task_description.lower()
        steps: List[Dict[str, Any]] = []
        url = self._extract_url_or_domain(task_description)
        
        # Открытие браузера и навигация
        if any(k in td for k in ["открой", "запусти", "перейди"]) and ("браузер" in td or url):
            steps.append({"step": 1, "description": "инициализация браузера", "tool": "initialize_browser", "args": {"headless": False}})
            if url:
                steps.append({"step": 2, "description": f"переход на {url}", "tool": "navigate_to_url", "args": {"url": url, "wait_for_element": "body", "timeout": 20}})
                steps.append({"step": 3, "description": "подтверждение открытия страницы", "tool": "take_screenshot", "args": {"filename": "opened.png"}})
            return steps
        
        # Поиск на сайте (например, вакансии на avito)
        if any(k in td for k in ["найди", "найти", "ищи", "поиск"]) and url:
            steps.append({"step": 1, "description": "инициализация браузера", "tool": "initialize_browser", "args": {"headless": False}})
            steps.append({"step": 2, "description": f"переход на {url}", "tool": "navigate_to_url", "args": {"url": url, "wait_for_element": "body", "timeout": 20}})
            
            # Извлекаем поисковый запрос из задачи
            search_query = task_description
            # Убираем упоминания сайта и команды
            for word in ["найди", "найти", "ищи", "поиск", "на", "avito.ru", "avito", "объявление", "объявления", "вакансия", "вакансии"]:
                search_query = search_query.replace(word, "").strip()
            
            # Если задача требует найти несколько элементов (например, "два объявления")
            import re
            count_match = re.search(r'(\d+)\s+(объявлени|ваканси)', td)
            count = int(count_match.group(1)) if count_match else 1
            
            # Для avito - ищем поле поиска и заполняем его
            if "avito" in td.lower():
                steps.append({"step": 3, "description": "поиск поля ввода поиска", "tool": "extract_text_from_page", "args": {"selectors": ["input[type='search']", "input[placeholder*='поиск']", ".suggest-input"], "text_patterns": []}})
                steps.append({"step": 4, "description": f"заполнение поискового запроса: {search_query}", "tool": "fill_form", "args": {"form_fields": {"input[type='search']": search_query, "input[placeholder*='поиск']": search_query}, "submit_selector": "button[type='submit']"}})
                steps.append({"step": 5, "description": "ожидание загрузки результатов", "tool": "navigate_to_url", "args": {"url": f"{url}/search?q={search_query.replace(' ', '+')}", "wait_for_element": "body", "timeout": 20}})
                steps.append({"step": 6, "description": f"извлечение {count} объявлений", "tool": "extract_text_from_page", "args": {"selectors": [".items-items-kAJAg", ".item", "[data-marker='item']"], "text_patterns": [search_query]}})
                steps.append({"step": 7, "description": "скриншот результатов поиска", "tool": "take_screenshot", "args": {"filename": "search_results.png"}})
            else:
                steps.append({"step": 3, "description": f"поиск: {search_query}", "tool": "extract_text_from_page", "args": {"selectors": ["body"], "text_patterns": [search_query]}})
                steps.append({"step": 4, "description": "скриншот результатов", "tool": "take_screenshot", "args": {"filename": "search_results.png"}})
            return steps
        
        # Запуск калькулятора
        if any(k in td for k in ["запусти", "открой"]) and any(k in td for k in ["калькулятор", "calc", "calculator"]):
            steps.append({"step": 1, "description": "запуск калькулятора", "tool": "open_application", "args": {"app_name": "calc"}})
            return steps
        
        # Работа с камерой
        if any(k in td for k in ["включи", "открой"]) and any(k in td for k in ["вебкамеру", "камера", "webcam"]):
            steps.append({"step": 1, "description": "открыть камеру", "tool": "open_camera", "args": {}})
            steps.append({"step": 2, "description": "сделать фото", "tool": "take_photo", "args": {"filename": "camera.png"}})
            return steps

        # Запуск произвольного приложения (универсальная стратегия)
        if any(k in td for k in ["запусти", "открой"]) and any(k in td for k in ["приложение", "программу", "app", "application", "telegram", "notepad", "calc"]):
            # Пытаемся извлечь предполагаемое имя приложения из текста
            app_name = None
            tokens = task_description.split()
            for t in tokens:
                if any(x in t.lower() for x in ["telegram", "notepad", "calc", ".exe"]):
                    app_name = t.strip('"')
                    break
            # Шаги: проверка процессов, расширенный запуск, fallback: через ярлык на рабочем столе
            steps.append({"step": 1, "description": "проверка запущенных процессов", "tool": "list_processes", "args": {"name_filter": app_name or ""}})
            steps.append({"step": 2, "description": "попытка запуска через системные стратегии", "tool": "open_application_advanced", "args": {"app_name": app_name or ""}})
            steps.append({"step": 3, "description": "свернуть все окна", "tool": "minimize_all_windows", "args": {}})
            steps.append({"step": 4, "description": "найти ярлык на рабочем столе", "tool": "locate_app_icon_on_desktop", "args": {"app_name": app_name or ""}})
            steps.append({"step": 5, "description": "запуск через клик по ярлыку", "tool": "click_at_coordinates", "args": {"x": 500, "y": 300}})
            return steps

        return []

    def run_task(self, task_description: str, auto_execute: bool = True, stop_on_failure: bool = True) -> Dict[str, Any]:
        """
        Входная точка: получает текст задачи, запрашивает план у LLM и (опционально) выполняет его.
        Сохраняет результат в историю.
        """
        logger.info(f"📝 Новый запрос задачи: {task_description}")
        entry = {
            "timestamp": datetime.now().isoformat(),
            "description": task_description,
            "category": self.analyze_task(task_description),
            "plan": None,
            "execution": None
        }

        # Создаём план
        plan = self.create_task_plan(task_description)
        entry["plan"] = plan

        if not plan:
            entry["execution"] = {"error": "План не создан или пуст"}
            self._append_history(entry)
            return entry

        if auto_execute:
            execution = self.execute_plan(plan, stop_on_failure=stop_on_failure, original_task=task_description, iterative=True)
            entry["execution"] = execution
        else:
            entry["execution"] = {"status": "not_executed", "message": "auto_execute=False"}

        self._append_history(entry)
        return entry

    def _append_history(self, entry: Dict[str, Any]) -> None:
        """Добавляет запись в локальную историю и сохраняет в файл."""
        try:
            self.task_history.append(entry)
            hist_path = Path(config.DOCUMENTS_DIR) / "task_history.json"
            # Сериализуем в строку — write_file в проекте ожидает str в качестве контента
            serialized = json.dumps(self.task_history, ensure_ascii=False, indent=2)
            self.fs_manager.write_file(str(hist_path), serialized, overwrite=True)
            logger.info(f"💾 История сохранена: {hist_path}")
        except Exception as e:
            logger.error(f"❌ Не удалось сохранить историю задач: {e}")

    def initialize_agent(self, init_browser: bool = False) -> Dict[str, Any]:
        """Инициализация окружения агента: Ollama + опционально браузер"""
        result: Dict[str, Any] = {"ollama": None, "browser": None}
        try:
            ok = check_ollama()
            result["ollama"] = {"available": bool(ok)}
        except Exception as e:
            result["ollama"] = {"available": False, "error": str(e)}

        if init_browser:
            try:
                br = initialize_browser()
                result["browser"] = {"initialized": bool(br)}
            except Exception as e:
                result["browser"] = {"initialized": False, "error": str(e)}

        return result


def _simple_cli():
    """
    Простой CLI для тестирования агента:
    запускается, если app.py вызван как __main__.
    """
    agent = AIAgent()
    print("AI Agent (simple CLI). Введите задачу или 'exit' для выхода.")
    # инициализируем Ollama (информативно)
    init_info = agent.initialize_agent(init_browser=False)
    print(f"Инициализация: {init_info}")

    try:
        while True:
            task = input("\nЗадача> ").strip()
            if not task:
                continue
            if task.lower() in ("exit", "quit"):
                break
            # запускаем задачу синхронно
            res = agent.run_task(task, auto_execute=True)
            print(json.dumps(res, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        print("\nВыход.")
    except Exception as e:
        logger.error(f"❌ Ошибка в CLI: {e}")


if __name__ == "__main__":
    _simple_cli()
