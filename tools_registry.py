TOOLS = [
    {"name": "initialize_browser", "description": "Инициализировать браузер", "parameters": {"headless": "режим без UI", "use_existing": "использовать открытый браузер", "cdp_url": "CDP endpoint", "debug_port": "порт отладки"}, "aliases": ["запусти браузер", "открой браузер", "init browser"], "keywords": ["browser", "playwright", "session", "headless", "cdp"], "args_schema": {"headless": "bool?", "use_existing": "bool?", "cdp_url": "string?", "debug_port": "int?"}},
    {"name": "search_web", "description": "Поиск информации в интернете", "parameters": {"query": "поисковый запрос", "search_engines": "список поисковиков", "max_results": "максимум результатов"}, "aliases": ["поиск в интернете", "найди в сети", "web search"], "keywords": ["search", "google", "bing", "results"], "args_schema": {"query": "string", "search_engines": "string[]?", "max_results": "int?"}},
    {"name": "navigate_to_url", "description": "Переход по URL", "parameters": {"url": "адрес страницы", "wait_for_element": "CSS селектор", "timeout": "таймаут"}, "aliases": ["открой сайт", "перейди на страницу", "go to url"], "keywords": ["navigate", "url", "open", "page"], "args_schema": {"url": "string", "wait_for_element": "string?", "timeout": "int?"}},
    {"name": "take_screenshot", "description": "Снимок экрана браузера", "parameters": {"filename": "имя файла", "directory": "папка"}, "aliases": ["сделай скрин", "снимок экрана", "screen shot"], "keywords": ["screenshot", "capture", "image", "png", "jpeg"], "args_schema": {"filename": "string", "directory": "string?"}},
    {"name": "extract_text_from_page", "description": "Извлечение текста со страницы", "parameters": {"selectors": "CSS селекторы", "text_patterns": "регулярные выражения"}, "aliases": ["получить текст", "парсинг текста", "extract text"], "keywords": ["text", "selectors", "regex", "content"], "args_schema": {"selectors": "string[]?", "text_patterns": "string[]?"}},
    {"name": "find_contact_info", "description": "Поиск контактной информации на странице", "parameters": {"contact_types": "типы (phone, email, address)"}, "aliases": ["найти контакты", "извлечь email/телефон", "contact info"], "keywords": ["phone", "email", "address", "contacts"], "args_schema": {"contact_types": "string[]?"}},
    {"name": "click_element", "description": "Нажатие на элемент", "parameters": {"selector": "CSS селектор", "wait_after": "задержка"}, "aliases": ["нажми кнопку", "кликни по элементу", "click"], "keywords": ["click", "button", "selector", "xpath"], "args_schema": {"selector": "string", "by": "string?", "timeout": "int?", "wait_after": "float?"}},
    {"name": "fill_form", "description": "Заполнение формы", "parameters": {"fields": "словарь полей", "submit": "нужно ли отправлять"}, "aliases": ["заполни форму", "ввод данных", "form fill"], "keywords": ["form", "input", "submit", "fields"], "args_schema": {"form_fields": "record<string,string>", "submit_selector": "string?"}},
    {"name": "scroll_page", "description": "Прокрутка страницы", "parameters": {"amount": "величина", "direction": "направление"}, "aliases": ["прокрути вниз", "scroll down", "scroll up"], "keywords": ["scroll", "viewport", "page"], "args_schema": {"direction": "string?", "amount": "int?"}},
    {"name": "get_page_source", "description": "Получение HTML страницы", "parameters": {"trim_length": "ограничение длины HTML"}, "aliases": ["html код", "исходный код страницы", "page html"], "keywords": ["html", "source", "dom", "content"], "args_schema": {"trim_length": "int?"}},
    {"name": "execute_javascript", "description": "JS в браузере", "parameters": {"script": "код"}, "aliases": ["выполни js", "run javascript", "eval js"], "keywords": ["javascript", "evaluate", "script"], "args_schema": {"script": "string"}},
    {"name": "close_browser", "description": "Закрытие браузера", "parameters": {}, "aliases": ["закрой браузер", "close", "shutdown browser"], "keywords": ["close", "browser", "end", "session"], "args_schema": {}},

    {"name": "read_file", "description": "Чтение файла", "parameters": {"path": "путь"}, "aliases": ["прочитай файл", "открой файл", "read"], "keywords": ["file", "read", "text", "content"], "args_schema": {"path": "string"}},
    {"name": "write_file", "description": "Запись файла", "parameters": {"path": "путь", "content": "содержимое", "overwrite": "перезапись"}, "aliases": ["запиши файл", "сохрани", "write"], "keywords": ["file", "write", "save", "overwrite"], "args_schema": {"path": "string", "content": "string", "overwrite": "bool?"}},
    {"name": "write_csv_file", "description": "Запись данных в CSV таблицу", "parameters": {"path": "путь к CSV файлу", "data": "список словарей с данными", "headers": "заголовки колонок (опционально)", "overwrite": "перезапись"}, "aliases": ["сохрани таблицу", "csv", "таблица"], "keywords": ["csv", "table", "spreadsheet", "data", "rows", "columns"], "args_schema": {"path": "string", "data": "array<object>", "headers": "string[]?", "overwrite": "bool?"}},
    {"name": "delete_file", "description": "Удаление файла", "parameters": {"path": "путь"}, "aliases": ["удали файл", "remove", "delete"], "keywords": ["file", "delete", "remove"], "args_schema": {"path": "string"}},
    {"name": "list_directory", "description": "Список файлов", "parameters": {"path": "путь"}, "aliases": ["список папки", "посмотри директорию", "ls"], "keywords": ["directory", "list", "files"], "args_schema": {"path": "string"}},
    {"name": "copy_file", "description": "Копирование файла", "parameters": {"src": "источник", "dst": "назначение"}, "aliases": ["скопируй файл", "copy"], "keywords": ["file", "copy", "duplicate"], "args_schema": {"src": "string", "dst": "string"}},
    {"name": "move_file", "description": "Перемещение файла", "parameters": {"src": "источник", "dst": "назначение"}, "aliases": ["перемести файл", "перенеси", "move"], "keywords": ["file", "move", "rename"], "args_schema": {"src": "string", "dst": "string"}},
    {"name": "create_directory", "description": "Создание папки", "parameters": {"path": "путь"}, "aliases": ["создай папку", "mkdir"], "keywords": ["directory", "create", "folder"], "args_schema": {"path": "string"}},
    {"name": "get_file_info", "description": "Информация о файле", "parameters": {"path": "путь"}, "aliases": ["свойства файла", "размер файла", "stat"], "keywords": ["file", "info", "size", "metadata"], "args_schema": {"path": "string"}},

    {"name": "execute_system_command", "description": "Команда Windows", "parameters": {"command": "команда"}, "aliases": ["выполни команду", "powershell", "cmd"], "keywords": ["command", "powershell", "cmd", "run"], "args_schema": {"command": "string", "working_dir": "string?"}},
    {"name": "open_application", "description": "Открыть приложение", "parameters": {"app_name": "имя", "args": "аргументы"}, "aliases": ["запусти программу", "start app", "open app"], "keywords": ["application", "open", "start"], "args_schema": {"app_name": "string", "args": "string?"}},
    {"name": "open_application_advanced", "description": "Запуск приложения (несколько стратегий)", "parameters": {"app_name": "имя", "args": "аргументы"}, "aliases": ["запусти приложение", "open advanced"], "keywords": ["application", "start-process", "exe"], "args_schema": {"app_name": "string", "args": "string?"}},
    {"name": "find_executable", "description": "Найти путь к .exe", "parameters": {"app_name": "имя"}, "aliases": ["найди exe", "find exe"], "keywords": ["exe", "path", "search"], "args_schema": {"app_name": "string"}},
    {"name": "close_application", "description": "Закрыть приложение", "parameters": {"app_name": "имя приложения", "force": "принудительное завершение"}, "aliases": ["закрой программу", "kill process", "close app"], "keywords": ["application", "close", "kill", "taskkill"], "args_schema": {"app_name": "string", "force": "bool?"}},
    {"name": "list_processes", "description": "Список процессов", "parameters": {"name_filter": "фильтр по названию"}, "aliases": ["процессы", "tasklist", "process list"], "keywords": ["process", "list", "task"], "args_schema": {"name_filter": "string?"}},
    {"name": "get_system_info", "description": "Информация о системе", "parameters": {}, "aliases": ["система", "характеристики", "system info"], "keywords": ["system", "cpu", "memory", "disk"], "args_schema": {}},

    {"name": "open_camera", "description": "Открыть веб‑камеру", "parameters": {}, "aliases": ["камера", "webcam", "open camera"], "keywords": ["camera", "webcam", "photo"], "args_schema": {}},
    {"name": "take_photo", "description": "Сделать фото", "parameters": {"filename": "имя файла", "directory": "папка"}, "aliases": ["сделай фото", "snap", "capture"], "keywords": ["photo", "camera", "image"], "args_schema": {"filename": "string?", "directory": "string?"}},
    {"name": "start_voice_recording", "description": "Запись аудио", "parameters": {}, "aliases": ["диктофон", "запиши звук", "voice record"], "keywords": ["audio", "voice", "record"], "args_schema": {}},
    {"name": "stop_voice_recording", "description": "Остановить запись аудио", "parameters": {}, "aliases": ["останови запись", "закрыть диктофон", "stop record"], "keywords": ["audio", "voice", "stop"], "args_schema": {}},

    {"name": "analyze_image", "description": "Анализ изображения LLM", "parameters": {"path": "путь к файлу"}, "aliases": ["проанализируй изображение", "vision", "image analysis"], "keywords": ["image", "vision", "analyze", "qwen3-vl"], "args_schema": {"path": "string", "question": "string?"}},

    {"name": "schedule_task", "description": "Планировщик Windows", "parameters": {"time": "время", "command": "команда"}, "aliases": ["запланируй", "таймер", "schedule"], "keywords": ["schedule", "task", "timer", "delay"], "args_schema": {"action": "string", "delay_minutes": "int?", "delay_hours": "int?", "specific_time": "string?", "command": "string?", "filename": "string?", "custom_action": "string?"}},
    {"name": "schedule_recurring_task", "description": "Повторяющаяся задача", "parameters": {"every_minutes": "каждые N минут", "duration_hours": "продолжительность"}, "aliases": ["повтор", "recurring", "repeat"], "keywords": ["schedule", "recurring", "repeat"], "args_schema": {"action": "string", "every_minutes": "int", "duration_hours": "int?", "command": "string?", "filename": "string?", "custom_action": "string?"}},
    {"name": "list_scheduled_tasks", "description": "Список задач", "parameters": {}, "aliases": ["задачи", "расписание", "tasks"], "keywords": ["tasks", "scheduled", "list"], "args_schema": {}},
    {"name": "cancel_scheduled_task", "description": "Удалить задачу", "parameters": {"task_name": "имя задачи"}, "aliases": ["отмени задачу", "cancel task", "remove"], "keywords": ["cancel", "task", "remove"], "args_schema": {"task_id": "int"}},


    {"name": "create_python_script", "description": "Создать и выполнить Python скрипт", "parameters": {"code": "код Python", "filename": "имя файла"}, "aliases": ["создай скрипт", "python скрипт"], "keywords": ["python", "script", "execute"], "args_schema": {"code": "string", "filename": "string?"}},

    {"name": "click_by_coordinates", "description": "Клик по координатам на экране", "parameters": {"x": "координата X", "y": "координата Y"}, "aliases": ["клик по координатам", "click coordinates"], "keywords": ["click", "coordinates", "mouse"], "args_schema": {"x": "int", "y": "int"}},

    {"name": "type_text", "description": "Ввод текста с клавиатуры", "parameters": {"text": "текст для ввода"}, "aliases": ["введи текст", "input text"], "keywords": ["type", "text", "keyboard"], "args_schema": {"text": "string"}},
    {"name": "press_key", "description": "Нажатие клавиши", "parameters": {"key": "имя клавиши"}, "aliases": ["нажми клавишу", "press key"], "keywords": ["key", "press", "keyboard"], "args_schema": {"key": "string"}},

    {"name": "list_windows", "description": "Список всех окон", "parameters": {}, "aliases": ["все окна", "windows list"], "keywords": ["windows", "list", "applications"], "args_schema": {}},

# Универсальные функции (other_func.py)
{"name": "take_desktop_screenshot", "description": "Скриншот всего рабочего стола", "parameters": {"filename": "имя файла", "directory": "папка"}, "aliases": ["скриншот рабочего стола", "desktop screenshot"], "keywords": ["screenshot", "desktop", "screen"], "args_schema": {"filename": "string", "directory": "string?"}},

{"name": "click_at_coordinates", "description": "Клик по координатам на экране", "parameters": {"x": "координата X", "y": "координата Y", "button": "кнопка мыши", "clicks": "количество кликов"}, "aliases": ["клик по координатам", "click coordinates"], "keywords": ["click", "coordinates", "mouse", "x", "y"], "args_schema": {"x": "int", "y": "int", "button": "string?", "clicks": "int?"}},

{"name": "move_mouse", "description": "Перемещение курсора мыши", "parameters": {"x": "координата X", "y": "координата Y", "duration": "продолжительность"}, "aliases": ["перемести мышь", "move mouse"], "keywords": ["mouse", "move", "cursor"], "args_schema": {"x": "int", "y": "int", "duration": "float?"}},

{"name": "type_text", "description": "Ввод текста с клавиатуры", "parameters": {"text": "текст для ввода", "interval": "интервал между символами"}, "aliases": ["введи текст", "input text"], "keywords": ["type", "text", "keyboard", "input"], "args_schema": {"text": "string", "interval": "float?"}},
{"name": "press_key", "description": "Нажатие клавиши", "parameters": {"key": "имя клавиши", "presses": "количество нажатий"}, "aliases": ["нажми клавишу", "press key"], "keywords": ["key", "press", "keyboard"], "args_schema": {"key": "string", "presses": "int?"}},
    {"name": "press_hotkey", "description": "Горячие клавиши", "parameters": {"keys": "массив клавиш"}, "aliases": ["горячая клавиша", "hotkey"], "keywords": ["hotkey", "shortcut", "keys"], "args_schema": {"keys": "string[]"}},

{"name": "get_screen_resolution", "description": "Получение разрешения экрана", "parameters": {}, "aliases": ["разрешение экрана", "screen resolution"], "keywords": ["screen", "resolution", "display"], "args_schema": {}},

{"name": "get_mouse_position", "description": "Получение позиции курсора мыши", "parameters": {}, "aliases": ["позиция мыши", "mouse position"], "keywords": ["mouse", "position", "cursor"], "args_schema": {}},

{"name": "create_python_script", "description": "Создание Python скрипта", "parameters": {"code": "код Python", "filename": "имя файла", "directory": "папка"}, "aliases": ["создай скрипт", "python скрипт"], "keywords": ["python", "script", "code"], "args_schema": {"code": "string", "filename": "string", "directory": "string?"}},

{"name": "execute_python_script", "description": "Выполнение Python скрипта", "parameters": {"script_path": "путь к скрипту", "timeout": "таймаут"}, "aliases": ["запусти скрипт", "run python script"], "keywords": ["python", "execute", "script", "run"], "args_schema": {"script_path": "string", "timeout": "int?"}},

{"name": "get_active_window_info", "description": "Получение информации об активном окне", "parameters": {}, "aliases": ["активное окно", "current window"], "keywords": ["window", "active", "info"], "args_schema": {}},
{"name": "focus_window", "description": "Активировать и при необходимости развернуть окно приложения", "parameters": {"app_name": "имя процесса/приложения", "maximize": "развернуть окно"}, "aliases": ["активируй окно", "фокус окно", "maximize window"], "keywords": ["window", "focus", "maximize"], "args_schema": {"app_name": "string?", "maximize": "bool?"}},

{"name": "list_windows", "description": "Список всех окон", "parameters": {}, "aliases": ["все окна", "windows list"], "keywords": ["windows", "list", "applications"], "args_schema": {}},

{"name": "wait_for_seconds", "description": "Ожидание указанного количества секунд", "parameters": {"seconds": "секунды"}, "aliases": ["подожди", "wait"], "keywords": ["wait", "sleep", "delay"], "args_schema": {"seconds": "float"}},

{"name": "analyze_screen_region", "description": "Анализ региона экрана с помощью LLM", "parameters": {"x": "координата X", "y": "координата Y", "width": "ширина", "height": "высота", "question": "вопрос для анализа"}, "aliases": ["анализ региона", "screen region analysis"], "keywords": ["analyze", "region", "screen", "vision"], "args_schema": {"x": "int", "y": "int", "width": "int", "height": "int", "question": "string"}},

{"name": "minimize_all_windows", "description": "Свернуть все окна (Win+D)", "parameters": {}, "aliases": ["сверни окна", "win d"], "keywords": ["windows", "desktop", "hotkey"], "args_schema": {}},
{"name": "locate_app_icon_on_desktop", "description": "Найти ярлык приложения на рабочем столе", "parameters": {"app_name": "имя приложения"}, "aliases": ["найди ярлык", "icon locate"], "keywords": ["icon", "desktop", "coordinates"], "args_schema": {"app_name": "string"}},

{"name": "write_excel_file", "description": "Записать данные в Excel", "parameters": {"filepath": "путь", "data": "данные"}, "aliases": ["excel", "xlsx", "write excel"], "keywords": ["excel", "xlsx", "data"], "args_schema": {"filepath": "string", "data": "array<object>", "sheet_name": "string?", "overwrite": "bool?"}},
{"name": "draw_chart", "description": "Построить график из CSV", "parameters": {"csv_path": "путь к CSV", "x_column": "ось X", "y_column": "ось Y"}, "aliases": ["график", "chart", "plot"], "keywords": ["chart", "plot", "csv"], "args_schema": {"csv_path": "string", "x_column": "string", "y_column": "string", "output_image": "string?"}},




]