# function_factory.py (улучшенная версия)
# ====================================================================

"""
Создание и выполнение Python скриптов с улучшенной обработкой ошибок
и поддержкой различных окружений Python
"""

import subprocess
import sys
import os
from pathlib import Path
from typing import Dict, Optional, Any, List
import config

logger = config.logger


def _find_python_executable() -> str:
    """
    Находит корректный исполняемый файл Python
    Проверяет различные варианты и возвращает работающий
    """
    # Варианты для проверки
    python_variants = [
        sys.executable,  # Текущий интерпретатор (самый надежный)
        "python",
        "python3",
        "py",  # Python Launcher для Windows
        r"C:\Python312\python.exe",
        r"C:\Python311\python.exe",
        r"C:\Python310\python.exe",
        r"C:\Python39\python.exe",
        r"C:\Python38\python.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python312", "python.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python311", "python.exe"),
    ]
    
    # Проверяем каждый вариант
    for variant in python_variants:
        if not variant:
            continue
        
        try:
            # Пробуем запустить python --version
            result = subprocess.run(
                [variant, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            
            if result.returncode == 0:
                logger.debug(f"🐍 Найден Python: {variant} ({result.stdout.strip()})")
                return variant
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            continue
    
    # Если ничего не нашли, возвращаем текущий интерпретатор
    logger.warning("⚠️ Не удалось найти оптимальный Python, используем sys.executable")
    return sys.executable


def _validate_python_code(code: str) -> Dict[str, Any]:
    """
    Валидация Python кода перед сохранением
    Проверяет синтаксис без выполнения
    """
    try:
        compile(code, '<string>', 'exec')
        return {"valid": True}
    except SyntaxError as e:
        return {
            "valid": False,
            "error": f"Синтаксическая ошибка на строке {e.lineno}: {e.msg}",
            "line": e.lineno,
            "offset": e.offset
        }
    except Exception as e:
        return {
            "valid": False,
            "error": f"Ошибка компиляции: {str(e)}"
        }


def create_python_script(
    code: str, 
    filename: str, 
    directory: Optional[str] = None,
    validate: bool = True,
    add_shebang: bool = False,
    add_encoding: bool = True
) -> Dict[str, Any]:
    """
    Создает Python скрипт с валидацией и дополнительными опциями
    
    Args:
        code: Код Python для сохранения
        filename: Имя файла
        directory: Директория для сохранения (по умолчанию из config)
        validate: Проверять синтаксис перед сохранением
        add_shebang: Добавить shebang в начало файла
        add_encoding: Добавить объявление кодировки
    
    Returns:
        Dict с результатом операции
    """
    try:
        # Определение директории
        if directory is None:
            directory = str(config.DOCUMENTS_DIR)
        
        full_dir = Path(directory).resolve()
        full_dir.mkdir(parents=True, exist_ok=True)
        
        # Валидация и нормализация имени файла
        if not filename.strip():
            return {"error": "Имя файла не может быть пустым", "status": "error"}
        
        # Очистка имени файла от недопустимых символов
        safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
        safe_filename = safe_filename.strip()
        
        if not safe_filename:
            return {"error": "Имя файла содержит только недопустимые символы", "status": "error"}
        
        # Добавление расширения .py
        if not safe_filename.lower().endswith('.py'):
            safe_filename += '.py'
        
        file_path = full_dir / safe_filename
        
        # Проверка кода перед сохранением
        if validate:
            validation = _validate_python_code(code)
            if not validation.get("valid"):
                logger.error(f"❌ Невалидный Python код: {validation.get('error')}")
                return {
                    "error": f"Невалидный Python код: {validation.get('error')}",
                    "status": "error",
                    "validation": validation
                }
        
        # Формирование финального кода
        final_code_parts = []
        
        # Shebang для Linux/Mac (необязательно для Windows, но не помешает)
        if add_shebang:
            python_path = _find_python_executable()
            if sys.platform == "win32":
                final_code_parts.append("#!python")
            else:
                final_code_parts.append(f"#!{python_path}")
        
        # Объявление кодировки (важно для Python 2 и рекомендуется для Python 3)
        if add_encoding and not code.strip().startswith('#'):
            final_code_parts.append("# -*- coding: utf-8 -*-")
        
        final_code_parts.append(code)
        final_code = "\n".join(final_code_parts)
        
        # Сохранение файла
        with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(final_code)
        
        # Проверка что файл создан
        if not file_path.exists():
            return {"error": "Файл не был создан", "status": "error"}
        
        file_size = file_path.stat().st_size
        
        logger.info(f"✅ Python скрипт создан: {file_path} ({file_size} bytes)")
        
        return {
            "status": "success",
            "file_path": str(file_path),
            "filename": safe_filename,
            "code_length": len(code),
            "file_size": file_size,
            "validated": validate
        }
        
    except PermissionError as e:
        error_msg = f"Нет прав на запись в директорию: {directory}"
        logger.error(f"❌ {error_msg}")
        return {"error": error_msg, "status": "error"}
    
    except OSError as e:
        error_msg = f"Ошибка файловой системы: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"error": error_msg, "status": "error"}
    
    except Exception as e:
        error_msg = f"Ошибка создания Python скрипта: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"error": error_msg, "status": "error"}


def execute_python_script(
    script_path: str, 
    timeout: int = 30,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    working_dir: Optional[str] = None,
    capture_output: bool = True
) -> Dict[str, Any]:
    """
    Выполняет Python скрипт с расширенными опциями
    
    Args:
        script_path: Путь к скрипту
        timeout: Таймаут выполнения в секундах
        args: Аргументы командной строки для скрипта
        env: Дополнительные переменные окружения
        working_dir: Рабочая директория для выполнения
        capture_output: Захватывать ли stdout/stderr
    
    Returns:
        Dict с результатом выполнения
    """
    try:
        # Проверка существования скрипта
        path = Path(script_path)
        if not path.exists():
            error_msg = f"Скрипт не найден: {script_path}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg, "status": "error"}
        
        if not path.is_file():
            error_msg = f"Указанный путь не является файлом: {script_path}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg, "status": "error"}
        
        # Поиск Python интерпретатора
        python_exec = _find_python_executable()
        logger.info(f"🐍 Использую Python: {python_exec}")
        
        # Формирование команды
        cmd = [python_exec, str(path)]
        if args:
            cmd.extend(args)
        
        # Подготовка окружения
        script_env = os.environ.copy()
        if env:
            script_env.update(env)
        
        # Установка PYTHONIOENCODING для корректной работы с кириллицей
        script_env['PYTHONIOENCODING'] = 'utf-8'
        script_env['PYTHONLEGACYWINDOWSSTDIO'] = 'utf-8'
        
        # Определение рабочей директории
        cwd = working_dir if working_dir else str(path.parent)
        
        logger.info(f"🚀 Запуск скрипта: {path}")
        logger.debug(f"   Команда: {' '.join(cmd)}")
        logger.debug(f"   Рабочая директория: {cwd}")
        logger.debug(f"   Таймаут: {timeout}с")
        
        # Выполнение скрипта
        creation_flags = 0
        if sys.platform == "win32":
            # На Windows скрываем консольное окно если запускаем из GUI
            creation_flags = subprocess.CREATE_NO_WINDOW
        
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            encoding='utf-8',
            errors='replace',  # Заменяем невалидные символы вместо ошибки
            cwd=cwd,
            env=script_env,
            creationflags=creation_flags
        )
        
        # Обработка результата
        success = result.returncode == 0
        status = "success" if success else "error"
        
        stdout_preview = result.stdout[:5000] if result.stdout else ""
        stderr_preview = result.stderr[:5000] if result.stderr else ""
        
        # Обрезаем вывод если он слишком длинный
        stdout_truncated = len(result.stdout) > 5000 if result.stdout else False
        stderr_truncated = len(result.stderr) > 5000 if result.stderr else False
        
        if success:
            logger.info(f"✅ Скрипт выполнен успешно. Код возврата: {result.returncode}")
        else:
            logger.error(f"❌ Скрипт завершился с ошибкой. Код возврата: {result.returncode}")
            if stderr_preview:
                logger.error(f"   Stderr: {stderr_preview[:200]}")
        
        response = {
            "status": status,
            "returncode": result.returncode,
            "script": str(path),
            "success": success
        }
        
        if capture_output:
            response.update({
                "stdout": stdout_preview,
                "stderr": stderr_preview,
                "stdout_length": len(result.stdout) if result.stdout else 0,
                "stderr_length": len(result.stderr) if result.stderr else 0,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated
            })
        
        return response
        
    except subprocess.TimeoutExpired:
        error_msg = f"Скрипт превысил таймаут {timeout} секунд"
        logger.error(f"❌ {error_msg}")
        return {
            "error": error_msg,
            "status": "timeout",
            "timeout": timeout,
            "script": str(script_path)
        }
    
    except FileNotFoundError as e:
        error_msg = f"Python интерпретатор не найден: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {
            "error": error_msg,
            "status": "error",
            "suggestion": "Убедитесь что Python установлен и добавлен в PATH"
        }
    
    except PermissionError as e:
        error_msg = f"Нет прав на выполнение скрипта: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"error": error_msg, "status": "error"}
    
    except Exception as e:
        error_msg = f"Ошибка выполнения Python скрипта: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {
            "error": error_msg,
            "status": "error",
            "exception_type": type(e).__name__
        }


def create_and_execute_script(
    code: str,
    filename: str,
    directory: Optional[str] = None,
    timeout: int = 30,
    cleanup: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Комбинированная функция: создает и сразу выполняет скрипт
    
    Args:
        code: Python код
        filename: Имя файла
        directory: Директория
        timeout: Таймаут выполнения
        cleanup: Удалить файл после выполнения
        **kwargs: Дополнительные параметры для execute_python_script
    
    Returns:
        Dict с результатом создания и выполнения
    """
    # Создаем скрипт
    create_result = create_python_script(code, filename, directory)
    
    if create_result.get("status") != "success":
        return create_result
    
    script_path = create_result["file_path"]
    
    # Выполняем скрипт
    exec_result = execute_python_script(script_path, timeout, **kwargs)
    
    # Объединяем результаты
    result = {
        "creation": create_result,
        "execution": exec_result,
        "status": exec_result.get("status", "error")
    }
    
    # Удаляем файл если нужно
    if cleanup:
        try:
            Path(script_path).unlink()
            result["cleanup"] = "success"
            logger.info(f"🗑️ Временный скрипт удален: {script_path}")
        except Exception as e:
            result["cleanup"] = f"error: {str(e)}"
            logger.warning(f"⚠️ Не удалось удалить временный скрипт: {e}")
    
    return result


def test_python_environment() -> Dict[str, Any]:
    """
    Тестирование Python окружения
    Проверяет доступность интерпретатора и базовых возможностей
    """
    try:
        python_exec = _find_python_executable()
        
        # Проверка версии
        version_result = subprocess.run(
            [python_exec, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        
        version = version_result.stdout.strip() or version_result.stderr.strip()
        
        # Проверка установленных пакетов
        pip_result = subprocess.run(
            [python_exec, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        
        packages_available = pip_result.returncode == 0
        
        # Тестовое выполнение
        test_code = 'print("Hello from Python!")'
        test_result = subprocess.run(
            [python_exec, "-c", test_code],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        
        execution_works = test_result.returncode == 0
        
        logger.info(f"✅ Тест Python окружения пройден")
        
        return {
            "status": "success",
            "python_executable": python_exec,
            "version": version,
            "execution_works": execution_works,
            "pip_available": packages_available,
            "sys_executable": sys.executable,
            "sys_version": sys.version,
            "platform": sys.platform
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка тестирования Python окружения: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# Экспорт основных функций
__all__ = [
    'create_python_script',
    'execute_python_script',
    'create_and_execute_script',
    'test_python_environment'
]