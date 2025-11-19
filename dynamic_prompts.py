"""
Динамическое создание инструкций и вспомогательных промптов для AI агента.
Этот модуль содержит функции для автоматического создания интеллектуальных инструкций
на основе контекста задачи, истории выполнения и ошибок.
"""
from typing import Dict, List, Optional


def build_dynamic_solution_prompt(original_task: str, failed_step: Dict, executed_steps: List[Dict], forbidden_tools: Optional[List[str]] = None, guidance: Optional[str] = None) -> str:
    """Создаёт промпт для поиска радикально нового решения при повторных неудачах.
    
    Используется когда стандартные подходы не работают (3+ попытки).
    Побуждает модель найти альтернативные стратегии: новые функции, системные команды,
    анализ изображений, использование координат вместо селекторов.
    """
    failure_context = []
    for step in executed_steps[-5:]:
        if step.get("status") == "failed":
            failure_context.append(f"- {step.get('description')}: {step.get('result', {}).get('error', 'неизвестная ошибка')}")
    context_str = "\n".join(failure_context)
    forbidden_tools = forbidden_tools or []
    forbidden_str = ", ".join(forbidden_tools) if forbidden_tools else ""
    extra_guidance = guidance or ""
    return f"""
КРИТИЧЕСКАЯ СИТУАЦИЯ: Задача не решается после 3+ неудачных попыток.

ИСХОДНАЯ ЗАДАЧА: {original_task}

ИСТОРИЯ НЕУДАЧ (последние 5 попыток):
{context_str}

ПОСЛЕДНИЙ ПРОВАЛЬНЫЙ ШАГ:
- Описание: {failed_step.get('description')}
- Инструмент: {failed_step.get('tool')}
- Ошибка: {failed_step.get('result', {}).get('error', 'неизвестно')}

ЗАПРЕТ: НЕЛЬЗЯ использовать следующие инструменты для следующей попытки решения (выбирай альтернативы): {forbidden_str}

ДОП. УКАЗАНИЯ:
{extra_guidance}

ТРЕБУЕТСЯ РАДИКАЛЬНО НОВОЕ РЕШЕНИЕ. Рассмотри и выбери лучший подход:

1. **АНАЛИЗ СКРИНШОТОВ + КООРДИНАТЫ**: take_desktop_screenshot → analyze_screen_region/analyze_image → click_at_coordinates с абсолютными X,Y.
2. **СИСТЕМНЫЕ КОМАНДЫ WINDOWS**: PowerShell/CMD (Get-ItemProperty, tasklist, schtasks, robocopy).
3. **PYTHON/POWERSHELL СКРИПТ**: create_python_script → execute_python_script (pyautogui, requests, BeautifulSoup) или собственный PowerShell.
4. **ПОИСК ФАЙЛОВ/ПРИЛОЖЕНИЙ**: find_executable, locate_app_icon_on_desktop, read_file.
5. **ОНЛАЙН-АВТОМАТИЗАЦИЯ**: initialize_browser(use_existing=true) → navigate_to_url → fill_form/execute_javascript → take_screenshot + analyze_image.
6. **SCHEDULER/ОТЛОЖЕННЫЕ ДЕЙСТВИЯ**: schedule_task / schedule_recurring_task для фонового выполнения.

ВАЖНО:
- Не повторяй тот же сценарий.
- Комбинируй минимум два разных инструмента.
- Используй анализ изображений и координаты для любого GUI.
- После выбора подхода добавь fallback-план.
- solution_type ДОЛЖЕН быть уникальным и отражать стратегию (пример: "python_script_via_files", "browser_gui_hybrid").

Верни JSON с решением:
{{
    "solution_type": "уникальный_тип (например hybrid_gui_script)",
    "description": "подробное описание нового подхода",
    "reasoning": "почему этот подход сработает",
    "implementation": {{
        "type": "screenshot_analysis|command|script|coordinates|file_search|scheduler",
        "details": "точные инструкции (последовательность инструментов, аргументы)",
        "new_function_spec": {{
            "name": "имя_новой_функции",
            "description": "что делает",
            "parameters": ["param1", "param2"]
        }}
    }},
    "expected_result": "что должно получиться",
    "fallback_plan": ["резервный вариант 1", "резервный вариант 2"]
}}
"""


def build_ui_analysis_prompt(function_spec: Dict, context: str) -> str:
    
    return f"""
ЗАДАЧА ДЛЯ АНАЛИЗА ИНТЕРФЕЙСА:
{function_spec.get('description', '')}

КОНТЕКСТ ВЫПОЛНЕНИЯ:
{context}

АНАЛИЗИРУЙ СКРИНШОТ И:

1. **Найди все интерактивные элементы** (кнопки, поля ввода, ссылки)
2. **Определи точные координаты X,Y** для кликов (центр элемента)
3. **Выдели текст, который нужно вводить** в каждое поле
4. **Опиши последовательность действий** в логическом порядке
5. **Предложи CSS селекторы** если видны id/class элементов
6. **Отметь проблемные зоны** (если что-то не видно или неясно)

ВЕРНИ JSON:
{{
    "analysis": "подробный анализ интерфейса, что видишь на скриншоте",
    "elements": [
        {{
            "type": "button|input|link|text",
            "label": "видимый текст элемента",
            "coordinates": {{"x": 100, "y": 200}},
            "description": "что это делает",
            "action": "click|type|hover",
            "input_text": "текст для ввода если нужно"
        }}
    ],
    "sequence": [
        "описание первого действия и координаты",
        "описание второго действия",
        "..."
    ],
    "coordinates_found": true/false,
    "recommended_tools": ["click_at_coordinates", "type_text", "press_key"],
    "issues": ["проблема 1", "проблема 2"],
    "confidence": 0.8
}}

ВАЖНО: Координаты должны быть точными и указывать на центр кликаемого элемента!
"""


def build_task_decomposition_prompt(user_request: str) -> str:
    
    return f"""
ТЫ - ИНТЕЛЛЕКТУАЛЬНЫЙ AI АГЕНТ ДЛЯ WINDOWS

ЗАДАЧА ПОЛЬЗОВАТЕЛЯ:
{user_request}

ТВОЯ РОЛЬ:
1. Полностью понять что нужно сделать
2. Разбить на логические подзадачи
3. Выбрать оптимальный инструмент для каждой подзадачи
4. Предусмотреть возможные ошибки и fallback'и
5. Убедиться, что все части задачи будут выполнены

ДОСТУПНЫЕ ВОЗМОЖНОСТИ:
✅ Выполнение команд Windows (PowerShell, CMD)
✅ Управление браузером (открытие, навигация, заполнение форм)
✅ Работа с файлами (чтение, запись, поиск)
✅ Анализ изображений через LLM (скриншоты)
✅ Клики мышью по координатам и элементам
✅ Ввод текста и нажатие клавиш
✅ Создание и запуск Python скриптов
✅ Запуск/закрытие приложений
✅ Планирование задач

ВАЖНЫЕ ПРАВИЛА:
1. Если приложение нужно открыть - сначала попробовать через find_executable, затем open_application_advanced
2. Использовать веб-браузер для задач в интернете
3. Использовать системные команды для операций с ОС
4. При работе с файлами - учитывать права доступа и кодировки
5. Когда нужна точность - использовать анализ изображений
6. Комбинировать инструменты для решения сложных задач

ВЫХОДНОЙ ФОРМАТ - JSON план с шагами:
{{
    "understanding": "твоё понимание задачи в одной строке",
    "subtasks": ["подзадача 1", "подзадача 2", "..."],
    "approach": "высокоуровневый подход",
    "plan": [
        {{
            "step": 1,
            "description": "описание шага",
            "tool": "имя_инструмента",
            "args": {{"параметр": "значение"}},
            "expected_outcome": "что должно произойти"
        }}
    ],
    "potential_issues": ["проблема 1", "решение", "проблема 2", "решение"],
    "success_criteria": "как понять что задача выполнена"
}}

Помни: ты должен решить ЛЮБУЮ задачу, используя комбинацию доступных инструментов.
"""


def build_image_analysis_detailed_prompt(screenshot_path: str, task_context: str, specific_question: str = None) -> str:
    
    return f"""
АНАЛИЗ СКРИНШОТА В КОНТЕКСТЕ ЗАДАЧИ

СКРИНШОТ: {screenshot_path}

КОНТЕКСТ ЗАДАЧИ:
{task_context}

{"СПЕЦИФИЧЕСКИЙ ВОПРОС: " + specific_question if specific_question else ""}

ТВОЯ ЗАДАЧА - ДЕТАЛЬНЫЙ АНАЛИЗ:

1. **Описание видимого содержимого**: Что видишь на экране?
   - Открытое приложение/браузер?
   - Видимый текст, кнопки, поля?
   - Ошибки, предупреждения, диалоги?

2. **Анализ в контексте задачи**: Соответствует ли текущее состояние ожиданиям?
   - Загружена ли страница/приложение полностью?
   - Готово ли к выполнению следующего действия?

3. **Необходимые действия**: Что нужно сделать дальше?
   - Какие элементы кликнуть (с точными координатами)?
   - Какой текст ввести?
   - Какие клавиши нажать?

4. **Проблемы и решения**: Если есть препятствия?
   - Что неправильно?
   - Как это обойти?

ВЕРНИ JSON:
{{
    "visible_state": "описание что видишь",
    "status": "loaded|loading|error|blocked|ready",
    "matches_expectation": true/false,
    "issues_detected": ["проблема 1", "..."],
    "next_actions": [
        {{
            "action": "click|type|press|wait",
            "target": "описание элемента",
            "coordinates": {{"x": 100, "y": 200}},
            "input": "текст если нужно вводить",
            "reason": "почему это действие нужно"
        }}
    ],
    "task_progress": "% выполнено или этап",
    "confidence": 0.95,
    "notes": "дополнительные замечания"
}}
"""