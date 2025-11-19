# win-command-func.py____________________________________________________________________________________________________

"""
Модуль для выполнения системных команд Windows.

ФУНКЦИИ:
=========
- execute_command(): выполнить PowerShell/CMD команду
- open_application(): открыть приложение через встроенные команды
- open_application_advanced(): открыть приложение с несколькими стратегиями
- find_executable(): найти путь к .exe файлу (поиск по диску, .lnk разрешение)
- close_application(): закрыть приложение через taskkill
- list_processes(): получить список запущенных процессов
- get_system_info(): информация о системе (CPU, памяти, диске)
- take_desktop_screenshot(): скриншот всего рабочего стола
- click_at_coordinates(): клик мышью по координатам
- move_mouse(): перемещение курсора мыши
- type_text(): ввод текста с клавиатуры
- press_key(): нажатие отдельных клавиш
- press_hotkey(): комбинация горячих клавиш (Ctrl+C, Win+D и т.д.)
- get_screen_resolution(): разрешение экрана
- get_mouse_position(): текущая позиция курсора
- locate_app_icon_on_desktop(): найти ярлык приложения на рабочем столе через анализ скриншота
- open_camera(): открыть встроенную камеру Windows
- take_photo(): сделать фото через камеру
- start_voice_recording(): запустить диктофон
- stop_voice_recording(): остановить диктофон
- schedule_task(): запланировать одноразовую задачу
- schedule_recurring_task(): запланировать повторяющуюся задачу
- list_scheduled_tasks(): список всех планов задач
- cancel_scheduled_task(): отменить запланированную задачу
- minimize_all_windows(): свернуть все окна (Win+D)
- get_active_window_info(): информация об активном окне
- list_windows(): список всех открытых окон

НОРМАЛИЗАЦИЯ РЕЗУЛЬТАТОВ:
========================
Все функции возвращают Dict с полями:
{
    "status": "success|error|partial",
    "error": null или сообщение об ошибке,
    "stdout": вывод команды,
    "stderr": ошибки вывода,
    "file_path": путь к файлу (если применимо),
    ... специфичные для функции поля
}

КОДИРОВАНИЕ:
============
Все субпроцессы используют encoding='utf-8' и errors='replace'
для безопасной работы с русским текстом и спецсимволами.
"""
import subprocess
import os
import sys
import time
import psutil
import ctypes
from ctypes import wintypes
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
import threading
import config
from pathlib import Path
from run_check_model import analyze_image

logger = config.logger

def normalize_command_result(result: Any, tool_name: str = "system_command") -> Dict[str, Any]:
    """Нормализует результаты команд в единую форму {status, error, stdout, stderr}"""
    try:
        if result is None:
            return {"status": "error", "error": "no result", "stdout": "", "stderr": ""}
        
        if isinstance(result, dict):
            res = dict(result)
            st = res.get("status")
            if st is None:
                st = "error" if res.get("error") else "success"
            res["status"] = str(st)
            if "error" not in res:
                res["error"] = None
            res["stdout"] = "" if res.get("stdout") is None else str(res.get("stdout"))
            res["stderr"] = "" if res.get("stderr") is None else str(res.get("stderr"))
            return res
        
        return {"status": "success", "error": None, "stdout": str(result), "stderr": ""}
    except Exception:
        return {"status": "error", "error": "normalization_failed", "stdout": "", "stderr": ""}

class WindowsCommandManager:
    """Управление системными командами Windows"""
    
    def __init__(self):
        self.running_processes = {}
        self.scheduled_tasks = {}
        self.task_counter = 0
        self.recurring_tasks = {}
        self.enum_windows_cache = {}

    def wait_for_seconds(self, seconds: float) -> Dict[str, Any]:
        """Ожидает указанное количество секунд"""
        logger.info(f"⏰ Ожидание {seconds} секунд")
        
        try:
            time.sleep(seconds)
            
            logger.info(f"✅ Ожидание завершено: {seconds} секунд")
            
            return {
                "status": "success",
                "wait_time": seconds,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ Ошибка во время ожидания: {str(e)}")
            return {"error": f"Ошибка во время ожидания: {str(e)}"}
    
    def analyze_screen_region(self, x: int, y: int, width: int, height: int,
                            question: str) -> Dict[str, Any]:
        """Анализирует регион экрана с помощью LLM"""
        logger.info(f"🔍 Анализ региона экрана: ({x}, {y}) {width}x{height}")
        
        try:
            # Сначала делаем скриншот региона
            import pyautogui
            screenshot = pyautogui.screenshot(region=(x, y, width, height))
            
            # Сохраняем временный файл
            temp_dir = Path(config.TEMP_DIR)
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = temp_dir / f"region_analysis_{int(time.time())}.png"
            screenshot.save(str(temp_file))
            
            # Используем analyze_image для анализа
            result = analyze_image(str(temp_file), question)
            
            # Очищаем временный файл
            try:
                temp_file.unlink()
            except:
                pass
            
            logger.info("✅ Анализ региона экрана завершен")
            
            return {
                "status": "success",
                "region": {"x": x, "y": y, "width": width, "height": height},
                "analysis": result.get('analysis', ''),
                "question": question
            }
        except ImportError:
            return {"error": "PyAutoGUI не установлен для создания скриншота региона"}
        except Exception as e:
            logger.error(f"❌ Ошибка анализа региона экрана: {str(e)}")
            return {"error": f"Ошибка анализа региона экрана: {str(e)}"}
        
    def execute_command(self, command: str, working_dir: Optional[str] = None,
                       timeout: int = 60, shell: bool = True) -> Dict[str, Any]:
        """Выполняет системную команду"""
        # Санитизация входа
        try:
            if not isinstance(command, str):
                if isinstance(command, dict):
                    cmd_candidate = command.get("command") or command.get("text") or command.get("cmd")
                    command = str(cmd_candidate) if cmd_candidate is not None else str(command)
                else:
                    command = str(command)
        except Exception:
            command = str(command)

        logger.info(f"⚙️ Выполнение команды: {command}")
        
        # Проверка на запрещённые команды
        for blocked in config.SECURITY_CONFIG['blocked_commands']:
            try:
                b = str(blocked).lower()
                c = str(command).lower()
                if b in c:
                    logger.error(f"❌ Запрещённая команда: {command}")
                    return normalize_command_result({"error": f"Команда заблокирована в целях безопасности: {blocked}"})
            except Exception:
                continue
        
        try:
            # Используем cwd вместо chdir для безопасности
            cmd_cwd = working_dir if working_dir else None

            # Выполнение через PowerShell для лучшей совместимости.
            # Формируем команду как строку и запускаем PowerShell без shell=True,
            # чтобы не смешивать list + shell=True поведение.
            ps_command = f"chcp 65001 > $null; {command}"

            try:
                result = subprocess.run(
                    ["powershell", "-Command", ps_command],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    shell=False,
                    timeout=timeout,
                    cwd=cmd_cwd
                )
            except TypeError:
                # На случай необычной среды — fallback на строковый вызов через shell
                result = subprocess.run(
                    f"powershell -Command \"{ps_command}\"",
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    shell=True,
                    timeout=timeout,
                    cwd=cmd_cwd
                )

            logger.info(f"✅ Команда выполнена. Код выхода: {result.returncode}")

            # Если команда не удалась и это 'start "..."', попробуем явный Start-Process
            if result.returncode != 0 and command.strip().lower().startswith('start'):
                try:
                    import re
                    matches = re.findall(r'"([^"]*)"', command)
                    exe_path = None
                    # Ищем последний непустой матч в кавычках (например start "" "C:\..." )
                    for s in reversed(matches):
                        if s and s.strip():
                            exe_path = s.strip()
                            break
                    if not exe_path:
                        # Попробуем взять последнюю часть после split как запасной вариант
                        parts = command.split()
                        if len(parts) >= 2:
                            exe_path = parts[-1].strip('"')

                    if exe_path:
                        logger.debug(f"⚙️ Попытка альтернативного запуска через Start-Process: {exe_path}")
                        ps_alt = f"Start-Process -FilePath \"{exe_path}\" -WindowStyle Normal"
                        alt = subprocess.run(
                            ["powershell", "-Command", f"chcp 65001 > $null; {ps_alt}"],
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace',
                            shell=False,
                            timeout=timeout,
                            cwd=cmd_cwd
                        )
                        logger.info(f"✅ Альтернативная команда выполнена. Код выхода: {alt.returncode}")
                        return {
                            "status": "success" if alt.returncode == 0 else "error",
                            "command": command,
                            "returncode": alt.returncode,
                            "stdout": (alt.stdout[:5000] if alt.stdout is not None else ""),
                            "stderr": (alt.stderr[:5000] if alt.stderr is not None else ""),
                            "execution_time": datetime.now().isoformat(),
                            "fallback_used": "Start-Process"
                        }
                except Exception:
                    logger.debug("Не удалось выполнить альтернативный запуск Start-Process")

            return {
                "status": "success" if result.returncode == 0 else "error",
                "command": command,
                "returncode": result.returncode,
                "stdout": (result.stdout[:5000] if result.stdout is not None else ""),
                "stderr": (result.stderr[:5000] if result.stderr is not None else ""),
                "execution_time": datetime.now().isoformat()
            }
            
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Таймаут выполнения команды: {timeout}с")
            return {"error": f"Команда превысила таймаут {timeout} секунд"}
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения команды: {str(e)}")
            return {"error": f"Ошибка выполнения команды: {str(e)}"}
    
    def open_application(self, app_name: str, args: str = "") -> Dict[str, Any]:
        """Открывает приложение"""
        # Санитизация входов
        try:
            if not isinstance(app_name, str):
                if isinstance(app_name, dict):
                    app_candidate = app_name.get("app_name") or app_name.get("application") or app_name.get("name")
                    app_name = str(app_candidate) if app_candidate is not None else str(app_name)
                else:
                    app_name = str(app_name)
            if args is None:
                args = ""
            if not isinstance(args, str):
                if isinstance(args, dict):
                    args = args.get("args") if isinstance(args.get("args"), str) else ""
                else:
                    args = str(args)
        except Exception:
            app_name = str(app_name)
            args = str(args) if args is not None else ""

        logger.info(f"🚀 Открытие приложения: {app_name}")
        
        try:
            # Проверка встроенных приложений Windows
            low = str(app_name).lower()
            if low in config.WINDOWS_COMMANDS:
                if 'open' in config.WINDOWS_COMMANDS[low]:
                    command = config.WINDOWS_COMMANDS[low]['open']
                else:
                    command = config.WINDOWS_COMMANDS[low]
            else:
                # Попытка открыть как обычное приложение
                command = f"start {app_name} {args}".strip()
            
            result = self.execute_command(command, timeout=10)
            
            if result.get("status") == "success":
                logger.info(f"✅ Приложение открыто: {app_name}")
                return {
                    "status": "success",
                    "application": app_name,
                    "message": f"Приложение {app_name} запущено"
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"❌ Ошибка открытия приложения: {str(e)}")
            return {"error": f"Ошибка открытия приложения: {str(e)}"}
    
    def close_application(self, app_name: str, force: bool = True) -> Dict[str, Any]:
        """Закрывает приложение"""
        # Санитизация входов
        try:
            if not isinstance(app_name, str):
                if isinstance(app_name, dict):
                    app_candidate = app_name.get("app_name") or app_name.get("application") or app_name.get("name")
                    app_name = str(app_candidate) if app_candidate is not None else str(app_name)
                else:
                    app_name = str(app_name)
        except Exception:
            app_name = str(app_name)

        logger.info(f"🔴 Закрытие приложения: {app_name}")
        
        try:
            # Проверка встроенных приложений
            low = str(app_name).lower()
            if low in config.WINDOWS_COMMANDS:
                if 'close' in config.WINDOWS_COMMANDS[low]:
                    command = config.WINDOWS_COMMANDS[low]['close']
                    return self.execute_command(command)
            
            # Закрытие через taskkill
            force_flag = "/F" if force else ""
            
            # Пробуем по имени процесса
            if not app_name.endswith('.exe'):
                app_name_exe = f"{app_name}.exe"
            else:
                app_name_exe = app_name
            
            command = f"taskkill {force_flag} /IM {app_name_exe}"
            result = self.execute_command(command)
            
            if result.get("status") == "success":
                logger.info(f"✅ Приложение закрыто: {app_name}")
                return {
                    "status": "success",
                    "application": app_name,
                    "message": f"Приложение {app_name} закрыто"
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"❌ Ошибка закрытия приложения: {str(e)}")
            return {"error": f"Ошибка закрытия приложения: {str(e)}"}
    
    def list_processes(self, name_filter: Optional[str] = None) -> Dict[str, Any]:
        """Список запущенных процессов"""
        logger.info("📋 Получение списка процессов")
        
        try:
            processes = []
            
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    proc_info = proc.info
                    
                    if name_filter and name_filter.lower() not in proc_info['name'].lower():
                        continue
                    
                    processes.append({
                        "pid": proc_info['pid'],
                        "name": proc_info['name'],
                        "cpu_percent": proc_info['cpu_percent'],
                        "memory_mb": round(proc_info['memory_info'].rss / (1024 * 1024), 2)
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            logger.info(f"✅ Найдено процессов: {len(processes)}")
            
            return {
                "status": "success",
                "count": len(processes),
                "processes": processes[:100]  # Ограничение для вывода
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка процессов: {str(e)}")
            return {"error": f"Ошибка получения списка процессов: {str(e)}"}
    
    def get_system_info(self) -> Dict[str, Any]:
        """Получает информацию о системе"""
        logger.info("💻 Получение информации о системе")
        
        try:
            import platform
            
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            info = {
                "status": "success",
                "os": platform.system(),
                "os_version": platform.version(),
                "os_release": platform.release(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": cpu_percent,
                "memory": {
                    "total_gb": round(memory.total / (1024**3), 2),
                    "available_gb": round(memory.available / (1024**3), 2),
                    "used_percent": memory.percent
                },
                "disk": {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "used_gb": round(disk.used / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "used_percent": disk.percent
                }
            }
            
            logger.info("✅ Информация о системе получена")
            return info
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о системе: {str(e)}")
            return {"error": f"Ошибка получения информации о системе: {str(e)}"}
    
    def open_camera(self) -> Dict[str, Any]:
        """Открывает встроенную камеру Windows"""
        logger.info("📷 Открытие камеры")
        return self.open_application("camera")
    
    def take_photo(self, output_path: Optional[str] = None) -> Dict[str, Any]:
        """Делает фото через камеру (требует открытую камеру)"""
        logger.info("📸 Создание фото через камеру")
        
        # Открываем камеру если не открыта
        camera_result = self.open_camera()
        
        if camera_result.get("status") != "success":
            return camera_result
        
        # Ждём загрузки камеры
        time.sleep(3)
        
        # Имитация нажатия кнопки захвата (Space или Enter в приложении камеры)
        # Используем AutoHotkey или pyautogui для автоматизации
        try:
            import pyautogui
            pyautogui.press('space')
            
            logger.info("✅ Фото сделано")
            
            return {
                "status": "success",
                "message": "Фото сделано. Проверьте папку Камера в библиотеке изображений.",
                "default_location": str(config.get_windows_documents_path() / "Pictures" / "Camera Roll")
            }
        except ImportError:
            return {
                "status": "partial",
                "message": "Камера открыта. Нажмите пробел для создания фото.",
                "note": "Для автоматического создания фото установите: pip install pyautogui"
            }
    
    def start_voice_recording(self) -> Dict[str, Any]:
        """Запускает запись звука"""
        logger.info("🎤 Запуск записи звука")
        return self.open_application("voice_recorder")

    def stop_voice_recording(self) -> Dict[str, Any]:
        """Останавливает запись звука"""
        logger.info("⏹ Остановка записи звука")
        try:
            cfg = config.WINDOWS_COMMANDS.get("voice_recorder", {})
            cmd = cfg.get("close")
            if cmd:
                return self.execute_command(cmd)
            return self.close_application("SoundRecorder.exe", force=True)
        except Exception as e:
            logger.error(f"❌ Ошибка остановки записи звука: {str(e)}")
            return {"error": f"Ошибка остановки записи звука: {str(e)}"}
    
    def schedule_task(self, action: str, delay_minutes: Optional[int] = None,
                     delay_hours: Optional[int] = None, specific_time: Optional[str] = None,
                     command: Optional[str] = None, filename: Optional[str] = None,
                     custom_action: Optional[str] = None) -> Dict[str, Any]:
        """Планирует задачу на выполнение"""
        logger.info(f"📅 Планирование задачи: {action}")
        
        task_id = self.task_counter
        self.task_counter += 1
        
        # Определяем время выполнения
        if specific_time:
            try:
                now = datetime.now()
                task_time = datetime.strptime(specific_time, "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                if task_time < now:
                    task_time += timedelta(days=1)
                delay_seconds = (task_time - now).total_seconds()
            except ValueError:
                return {"error": "Неверный формат времени. Используйте HH:MM"}
        elif delay_hours:
            delay_seconds = delay_hours * 3600
        elif delay_minutes:
            delay_seconds = delay_minutes * 60
        else:
            return {"error": "Не указано время выполнения"}
        
        # Создаём информацию о задаче
        task_info = {
            "id": task_id,
            "action": action,
            "scheduled_time": datetime.now() + timedelta(seconds=delay_seconds),
            "status": "scheduled",
            "command": command,
            "filename": filename,
            "custom_action": custom_action
        }
        
        # Запускаем таймер
        timer = threading.Timer(delay_seconds, self._execute_scheduled_task, [task_id])
        timer.daemon = True
        timer.start()
        
        task_info["timer"] = timer
        self.scheduled_tasks[task_id] = task_info
        
        logger.info(f"✅ Задача #{task_id} запланирована на {task_info['scheduled_time'].strftime('%H:%M:%S')}")
        
        return {
            "status": "success",
            "task_id": task_id,
            "action": action,
            "scheduled_time": task_info["scheduled_time"].strftime("%Y-%m-%d %H:%M:%S"),
            "delay_seconds": int(delay_seconds)
        }

    def schedule_recurring_task(self, action: str, every_minutes: int,
                                duration_hours: Optional[int] = None,
                                command: Optional[str] = None,
                                filename: Optional[str] = None,
                                custom_action: Optional[str] = None) -> Dict[str, Any]:
        """Запускает повторяющуюся задачу каждые N минут в течение указанного времени"""
        logger.info(f"⏱️ Запуск повторяющейся задачи: {action} каждые {every_minutes} мин")
        if every_minutes <= 0:
            return {"error": "every_minutes должен быть > 0"}
        task_id = self.task_counter
        self.task_counter += 1
        end_time = None
        if duration_hours and duration_hours > 0:
            end_time = datetime.now() + timedelta(hours=duration_hours)

        def _runner(tid: int):
            while True:
                if end_time and datetime.now() >= end_time:
                    break
                self._execute_scheduled_task(tid)
                # пересоздать заготовку для следующего запуска
                self.scheduled_tasks[tid]["status"] = "scheduled"
                time.sleep(every_minutes * 60)
            self.scheduled_tasks[tid]["status"] = "completed"

        info = {
            "id": task_id,
            "action": action,
            "status": "scheduled",
            "scheduled_time": datetime.now(),
            "command": command,
            "filename": filename,
            "custom_action": custom_action,
            "recurring": True,
            "every_minutes": every_minutes,
            "end_time": end_time
        }
        self.scheduled_tasks[task_id] = info
        thread = threading.Thread(target=_runner, args=(task_id,), daemon=True)
        thread.start()
        self.recurring_tasks[task_id] = thread
        return {
            "status": "success",
            "task_id": task_id,
            "recurring": True,
            "every_minutes": every_minutes,
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S") if end_time else None
        }
    
    def _execute_scheduled_task(self, task_id: int):
        """Выполняет запланированную задачу"""
        if task_id not in self.scheduled_tasks:
            return
        
        task = self.scheduled_tasks[task_id]
        
        if task.get("status") == "cancelled":
            return
        
        task["status"] = "executing"
        logger.info(f"🕐 Выполнение запланированной задачи #{task_id}: {task['action']}")
        
        try:
            action = task["action"]
            
            if action == "close_browser":
                from browser_function import close_browser
                result = close_browser()
            elif action == "take_screenshot":
                from browser_function import take_screenshot
                filename = task.get("filename", f"scheduled_{task_id}_{datetime.now().strftime('%H%M%S')}.png")
                result = take_screenshot(filename)
            elif action == "execute_command":
                result = self.execute_command(task["command"])
            elif action == "custom":
                result = {"status": "completed", "action": task["custom_action"]}
            else:
                result = {"error": f"Неизвестное действие: {action}"}
            
            task["result"] = result
            task["status"] = "completed"
            task["completed_time"] = datetime.now()
            
            if "timer" in task:
                del task["timer"]
            
            logger.info(f"✅ Задача #{task_id} выполнена")
            
        except Exception as e:
            task["status"] = "failed"
            task["error"] = str(e)
            if "timer" in task:
                del task["timer"]
            logger.error(f"❌ Ошибка выполнения задачи #{task_id}: {e}")
    
    def list_scheduled_tasks(self) -> Dict[str, Any]:
        """Список запланированных задач"""
        logger.info("📋 Список запланированных задач")
        
        active_tasks = {k: v for k, v in self.scheduled_tasks.items() 
                       if v["status"] in ["scheduled", "executing"]}
        completed_tasks = {k: v for k, v in self.scheduled_tasks.items() 
                          if v["status"] in ["completed", "failed"]}
        
        tasks_list = []
        for task_id, task in self.scheduled_tasks.items():
            task_info = {
                "id": task_id,
                "action": task["action"],
                "status": task["status"],
                "scheduled_time": task["scheduled_time"].strftime("%Y-%m-%d %H:%M:%S")
            }
            
            if "completed_time" in task:
                task_info["completed_time"] = task["completed_time"].strftime("%Y-%m-%d %H:%M:%S")
            
            if "command" in task and task["command"]:
                task_info["command"] = task["command"]
            
            tasks_list.append(task_info)
        
        return {
            "status": "success",
            "active_tasks": len(active_tasks),
            "completed_tasks": len(completed_tasks),
            "total_tasks": len(self.scheduled_tasks),
            "tasks": tasks_list
        }
    
    def cancel_scheduled_task(self, task_id: int) -> Dict[str, Any]:
        """Отменяет запланированную задачу"""
        logger.info(f"❌ Отмена задачи #{task_id}")
        
        if task_id not in self.scheduled_tasks:
            return {"error": f"Задача #{task_id} не найдена"}
        
        task = self.scheduled_tasks[task_id]
        
        if task["status"] != "scheduled":
            return {"error": f"Задача #{task_id} уже выполняется или завершена"}
        
        # Отменяем таймер
        if "timer" in task and hasattr(task["timer"], "cancel"):
            try:
                task["timer"].cancel()
                logger.info(f"✅ Таймер задачи #{task_id} отменён")
            except Exception as e:
                logger.error(f"❌ Ошибка отмены таймера: {e}")
        
        task["status"] = "cancelled"
        task["cancelled_time"] = datetime.now()
        
        if "timer" in task:
            del task["timer"]
        
        logger.info(f"✅ Задача #{task_id} отменена")
        
        return {
            "status": "success",
            "task_id": task_id,
            "message": f"Задача #{task_id} отменена"
        }

    def minimize_all_windows(self) -> Dict[str, Any]:
        try:
            import pyautogui
        except ImportError:
            return {"error": "PyAutoGUI не установлен. Установите: pip install pyautogui"}
        try:
            pyautogui.hotkey('win', 'd')
            return {"status": "success"}
        except Exception as e:
            return {"error": str(e)}

    def find_executable(self, app_name: str, use_cache: bool = True, search_all_drives: bool = False) -> Dict[str, Any]:
        """
        Интеллектуальный поиск исполняемого файла приложения.
        Использует кэш, Registry, стандартные папки, поиск по похожим названиям папок и .lnk файлам.
        
        Args:
            app_name: Имя приложения (например, 'Telegram' (Telegram Desktop), 'VLC', 'Notepad++')
            use_cache: Использовать кэш ранее найденных приложений
            search_all_drives: Полный поиск по всем дискам (медленнее, но полнее)
            
        Returns:
            Dict с 'status' и 'path' (или 'status': 'not_found')
        """
        try:
            exe_name = app_name if app_name.lower().endswith('.exe') else f"{app_name}.exe"
            
            # Кэш
            cache_key = f"{app_name.lower()}_{search_all_drives}"
            if use_cache and hasattr(self, '_app_cache') and cache_key in self._app_cache:
                logger.debug(f"✅ {app_name} найден в кэше: {self._app_cache[cache_key]['path']}")
                return self._app_cache[cache_key]
            
            if not hasattr(self, '_app_cache'):
                self._app_cache = {}
            
            # Расширённые пути поиска (включая D:\Programs)
            search_paths = [
                'C:\\Program Files',
                'C:\\Program Files (x86)',
                'D:\\Programs',
                '$env:LOCALAPPDATA',
                '$env:ProgramData',
                '$env:APPDATA',
                '$env:APPDATA + "\\Microsoft\\Windows\\Start Menu"',
                '$env:PUBLIC + "\\Desktop"',
                '$env:USERPROFILE + "\\Desktop"',
            ]
            
            paths_str = ','.join([f"'{p}'" for p in search_paths])
            
            # Попытка 1: Registry поиск (быстро)
            logger.debug(f"🔍 Попытка 1: Поиск {app_name} в Registry...")
            ps_registry = f'''
$regPaths = @(
    'HKLM:\\\\Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\App Paths',
    'HKCU:\\\\Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\App Paths',
    'HKLM:\\\\Software\\\\Wow6432Node\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\App Paths'
)
foreach($regPath in $regPaths) {{
    if(Test-Path $regPath) {{
        $appPath = Get-ItemProperty -Path "$regPath\\\\{exe_name}" -ErrorAction SilentlyContinue
        if($appPath -and $appPath.'(Default)') {{
            Write-Output $appPath.'(Default)'
            exit
        }}
    }}
}}
'''
            result = self.execute_command(ps_registry)
            if result.get("stdout", "").strip():
                found_path = result.get("stdout", "").strip().split('\n')[0].strip()
                logger.info(f"✅ Найден {app_name} в Registry: {found_path}")
                ret = {"status": "success", "path": found_path, "method": "registry"}
                self._app_cache[cache_key] = ret
                return ret
            
            # Попытка 2: Прямой поиск exe в стандартных папках
            logger.debug(f"🔍 Попытка 2: Поиск {app_name}.exe в стандартных папках...")
            ps_direct = f'''
$n="{exe_name}";
$paths=@({paths_str});
foreach($p in $paths){{
    if(Test-Path $p){{
        try{{
            $res=Get-ChildItem -Path $p -Filter $n -Recurse -ErrorAction SilentlyContinue -Force | Select-Object -First 1
            if($res){{Write-Output $res.FullName; exit}}
        }}catch{{}}
    }}
}}
'''
            result = self.execute_command(ps_direct)
            if result.get("stdout", "").strip():
                found_path = result.get("stdout", "").strip().split('\n')[0].strip()
                logger.info(f"✅ Найден {app_name} в стандартных папках: {found_path}")
                ret = {"status": "success", "path": found_path, "method": "exe_search"}
                self._app_cache[cache_key] = ret
                return ret
            
            # Попытка 3: Поиск по похожим названиям папок (Telegram -> Telegram Desktop)
            logger.debug(f"🔍 Попытка 3: Поиск по похожим названиям папок...")
            ps_similar = f'''
$appName="{app_name}";
$paths=@({paths_str});
foreach($p in $paths){{
    if(Test-Path $p){{
        try{{
            Get-ChildItem -Path $p -Directory -ErrorAction SilentlyContinue -Force | ForEach-Object {{
                $folder = $_.Name.ToLower()
                $app = $appName.ToLower()
                if($folder -like "*$app*" -or $folder -like "$($app.Replace(' ',''))*"){{
                    $appPath = $_.FullName
                    Get-ChildItem -Path $appPath -Filter "*.exe" -Recurse -ErrorAction SilentlyContinue | ForEach-Object {{
                        if($_.Name -like "*$app*" -or $_.BaseName -like "*$app*"){{
                            Write-Output $_.FullName
                            exit
                        }}
                    }}
                }}
            }}
        }}catch{{}}
    }}
}}
'''
            result = self.execute_command(ps_similar)
            if result.get("stdout", "").strip():
                found_path = result.get("stdout", "").strip().split('\n')[0].strip()
                logger.info(f"✅ Найден {app_name} по похожему названию папки: {found_path}")
                ret = {"status": "success", "path": found_path, "method": "folder_similarity"}
                self._app_cache[cache_key] = ret
                return ret
            
            # Попытка 4: Поиск в ярлыках (.lnk)
            logger.debug(f"🔍 Попытка 4: Поиск в ярлыках (.lnk)...")
            ps_lnk = f'''
$appName="{app_name}";
$n="{exe_name}";
$paths=@({paths_str});
foreach($p in $paths){{
    if(Test-Path $p){{
        try{{
            $lnks = Get-ChildItem -Path $p -Filter *.lnk -Recurse -ErrorAction SilentlyContinue -Force | Select-Object -First 300
            foreach($f in $lnks){{
                try{{
                    $shell = New-Object -ComObject WScript.Shell
                    $sc = $shell.CreateShortcut($f.FullName)
                    if($sc.TargetPath -and ($sc.TargetPath -like '*$appName*' -or [System.IO.Path]::GetFileName($sc.TargetPath) -ieq $n)){{
                        Write-Output $sc.TargetPath
                        exit
                    }}
                }}catch{{}}
            }}
        }}catch{{}}
    }}
}}
'''
            result = self.execute_command(ps_lnk)
            if result.get("stdout", "").strip():
                found_path = result.get("stdout", "").strip().split('\n')[0].strip()
                logger.info(f"✅ Найден {app_name} через ярлык: {found_path}")
                ret = {"status": "success", "path": found_path, "method": "shortcut"}
                self._app_cache[cache_key] = ret
                return ret
            
            # Попытка 5: Полный поиск по всем дискам (если разрешено и предыдущие не сработали)
            if search_all_drives:
                logger.debug(f"🔍 Попытка 5: Полный поиск по всем дискам...")
                ps_all_drives = f'''
$drives = Get-PSDrive -PSProvider FileSystem | Where-Object {{$_.Name -match '^[A-Z]$'}}
foreach($drive in $drives) {{
    try {{
        Get-ChildItem -Path "$($drive.Name):\\" -Filter "{exe_name}" -Recurse -ErrorAction SilentlyContinue -Force | Select-Object -First 1 | ForEach-Object {{
            Write-Output $_.FullName
            exit
        }}
    }} catch {{}}
}}
'''
                result = self.execute_command(ps_all_drives)
                if result.get("stdout", "").strip():
                    found_path = result.get("stdout", "").strip().split('\n')[0].strip()
                    logger.info(f"✅ Найден {app_name} при полном поиске: {found_path}")
                    ret = {"status": "success", "path": found_path, "method": "all_drives"}
                    self._app_cache[cache_key] = ret
                    return ret
            
            logger.warning(f"⚠️ {app_name} не найден ни в одной из папок")
            return {"status": "not_found"}
            
        except Exception as e:
            logger.error(f"❌ Ошибка при поиске {app_name}: {str(e)}")
            return {"error": str(e)}

    def open_application_advanced(self, app_name: str, args: str = "", search_all_drives: bool = False) -> Dict[str, Any]:
        """
        Расширенная функция открытия приложения с множественными стратегиями.
        
        Попытается открыть через:
        1. Стандартный метод (start command)
        2. find_executable() с поиском в стандартных папках (включая D:/Programs)
        3. Поиск по похожим названиям папок
        4. Поиск в ярлыках
        5. Полный поиск по всем дискам (если search_all_drives=True)
        6. Fallback на прямую команду start
        
        Args:
            app_name: Имя приложения
            args: Аргументы для приложения
            search_all_drives: Полный поиск по дискам при необходимости
            
        Returns:
            Dict с результатом выполнения
        """
        logger.info(f"🚀 Открытие приложения: {app_name}")
        result_list = []
        
        # Попытка 1: Стандартный метод
        logger.info(f"⚙️ Попытка 1: Стандартная команда 'start {app_name}'")
        result = self.execute_command(f"start {app_name}")
        result_normalized = normalize_command_result(result)
        result_list.append(result_normalized)
        
        if result_normalized.get("status") == "success":
            logger.info(f"✅ Приложение {app_name} успешно открыто (метод 1)")
            return result_normalized
        
        # Попытка 2: Поиск exe и запуск через PowerShell
        logger.info(f"⚙️ Попытка 2: Поиск исполняемого файла через find_executable...")
        exe_result = self.find_executable(app_name, use_cache=True, search_all_drives=False)
        result_list.append(exe_result)
        
        if exe_result.get("status") == "success":
            exe_path = exe_result.get("path")
            logger.info(f"✅ Найден путь: {exe_path} (метод: {exe_result.get('method', 'unknown')})")
            
            try:
                # Запуск через Start-Process
                cmd = f'Start-Process "{exe_path}" -WindowStyle Normal'
                if args:
                    cmd += f' -ArgumentList "{args}"'
                
                result = self.execute_command(cmd)
                if result.get("status") == "success":
                    logger.info(f"✅ Приложение {app_name} успешно открыто через exe (метод 2)")
                    return {"status": "success", "method": "powershell_exe", "path": exe_path}
                
                # Если не сработало через Start-Process, пробуем запустить напрямую через Popen
                import subprocess
                proc = subprocess.Popen(
                    f'"{exe_path}" {args}' if args else f'"{exe_path}"',
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, 'CREATE_NEW_CONSOLE') else 0
                )
                logger.info(f"✅ Приложение {app_name} запущено через Popen (метод 2b, PID: {proc.pid})")
                return {"status": "success", "method": "popen_exe", "path": exe_path, "pid": proc.pid}
                
            except Exception as e:
                logger.error(f"❌ Ошибка при запуске через PowerShell: {e}")
                result_list.append({"status": "error", "error": str(e)})
        
        # Попытка 3: Полный поиск по всем дискам (если разрешено)
        if search_all_drives:
            logger.info(f"⚙️ Попытка 3: Полный поиск по всем дискам...")
            exe_result = self.find_executable(app_name, use_cache=False, search_all_drives=True)
            result_list.append(exe_result)
            
            if exe_result.get("status") == "success":
                exe_path = exe_result.get("path")
                logger.info(f"✅ Найден при полном поиске: {exe_path}")
                
                try:
                    import subprocess
                    proc = subprocess.Popen(
                        f'"{exe_path}" {args}' if args else f'"{exe_path}"',
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, 'CREATE_NEW_CONSOLE') else 0
                    )
                    logger.info(f"✅ Приложение {app_name} открыто (метод 3, полный поиск, PID: {proc.pid})")
                    return {"status": "success", "method": "full_search_exe", "path": exe_path, "pid": proc.pid}
                except Exception as e:
                    logger.error(f"❌ Ошибка при запуске найденного exe: {e}")
                    result_list.append({"status": "error", "error": str(e)})
        
        # Попытка 4: Fallback на простую команду start
        logger.info(f"⚙️ Попытка 4: Fallback на простую команду start")
        result = self.execute_command(f"start {app_name} ")
        result_normalized = normalize_command_result(result)
        result_list.append(result_normalized)
        
        if result_normalized.get("status") == "success":
            logger.info(f"✅ Приложение {app_name} успешно открыто (метод 4, fallback)")
            return result_normalized
        
        # Все попытки провалились
        logger.error(f"❌ Не удалось запустить {app_name} ни одним методом")
        return {
            "status": "error",
            "error": f"Не удалось запустить {app_name}",
            "details": result_list,
            "stdout": "",
            "stderr": ""
        }

    def locate_app_icon_on_desktop(self, app_name: str) -> Dict[str, Any]:
        """Сворачивает окна, делает скриншот, просит LLM найти координаты ярлыка"""
        try:
            self.minimize_all_windows()
            shot = self.take_desktop_screenshot(filename=f"desktop_{int(time.time())}.png")
            if shot.get("status") != "success":
                return {"error": "Не удалось сделать скриншот рабочего стола"}
            path = shot.get("file_path")
            from run_check_model import analyze_image
            question = (
                f"Найди на скриншоте ярлык приложения '{app_name}'. Верни JSON: "
                f"{{\"coordinates\":[{{\"x\":X,\"y\":Y,\"action\":\"click\"}}],\"confidence\":0-1}}"
            )
            result = analyze_image(str(path), question)
            coords = None
            if isinstance(result, dict):
                data = result.get('analysis') or result
                # Попытка извлечь x,y
                import json as _json
                try:
                    parsed = data if isinstance(data, dict) else _json.loads(str(data))
                    arr = parsed.get('coordinates') if isinstance(parsed, dict) else None
                    if isinstance(arr, list) and arr:
                        c = arr[0]
                        if isinstance(c, dict) and 'x' in c and 'y' in c:
                            coords = (int(c['x']), int(c['y']))
                except Exception:
                    pass
            if not coords:
                return {"status": "partial", "image": path, "message": "Координаты не извлечены"}
            return {"status": "success", "image": path, "x": coords[0], "y": coords[1]}
        except Exception as e:
            return {"error": str(e)}
        
        
        
    def take_desktop_screenshot(self, filename: str, directory: Optional[str] = None) -> Dict[str, Any]:
        """Делает скриншот рабочего стола"""
        try:
            import pyautogui
        except ImportError:
            return {"error": "PyAutoGUI не установлен. Установите: pip install pyautogui"}
        try:
            if directory is None:
                directory = str(config.SCREENSHOTS_DIR)
            from pathlib import Path as _P
            full_dir = _P(directory)
            full_dir.mkdir(parents=True, exist_ok=True)
            if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
                filename += f".{config.SCREENSHOT_FORMAT}"
            file_path = full_dir / filename
            screenshot = pyautogui.screenshot()
            screenshot.save(str(file_path))
            return {"status": "success", "file_path": str(file_path), "size": file_path.stat().st_size, "resolution": f"{screenshot.width}x{screenshot.height}"}
        except Exception as e:
            logger.error(f"❌ Ошибка создания скриншота рабочего стола: {str(e)}")
            return {"error": f"Ошибка создания скриншота рабочего стола: {str(e)}"}

    def click_at_coordinates(self, x: int, y: int, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
        """Кликает по координатам"""
        try:
            import pyautogui
        except ImportError:
            return {"error": "PyAutoGUI не установлен. Установите: pip install pyautogui"}
        try:
            pyautogui.click(x=x, y=y, button=button, clicks=clicks)
            return {"status": "success", "coordinates": {"x": x, "y": y}, "button": button, "clicks": clicks}
        except Exception as e:
            logger.error(f"❌ Ошибка клика по координатам: {str(e)}")
            return {"error": f"Ошибка клика по координатам: {str(e)}"}

    def move_mouse(self, x: int, y: int, duration: float = 0.5) -> Dict[str, Any]:
        """Перемещает курсор мыши"""
        try:
            import pyautogui
        except ImportError:
            return {"error": "PyAutoGUI не установлен. Установите: pip install pyautogui"}
        try:
            pyautogui.moveTo(x, y, duration=duration)
            return {"status": "success", "coordinates": {"x": x, "y": y}, "duration": duration}
        except Exception as e:
            logger.error(f"❌ Ошибка перемещения мыши: {str(e)}")
            return {"error": f"Ошибка перемещения мыши: {str(e)}"}

    def type_text(self, text: str, interval: float = 0.1) -> Dict[str, Any]:
        """Вводит текст"""
        try:
            import pyautogui
        except ImportError:
            return {"error": "PyAutoGUI не установлен. Установите: pip install pyautogui"}
        try:
            pyautogui.write(text, interval=interval)
            return {"status": "success", "text_length": len(text), "interval": interval}
        except Exception as e:
            logger.error(f"❌ Ошибка ввода текста: {str(e)}")
            return {"error": f"Ошибка ввода текста: {str(e)}"}

    def press_key(self, key: str, presses: int = 1) -> Dict[str, Any]:
        """Нажимает клавишу"""
        try:
            import pyautogui
        except ImportError:
            return {"error": "PyAutoGUI не установлен. Установите: pip install pyautogui"}
        try:
            pyautogui.press(key, presses=presses)
            return {"status": "success", "key": key, "presses": presses}
        except Exception as e:
            logger.error(f"❌ Ошибка нажатия клавиши: {str(e)}")
            return {"error": f"Ошибка нажатия клавиши: {str(e)}"}

    def press_hotkey(self, keys: List[str]) -> Dict[str, Any]:
        try:
            import pyautogui
        except ImportError:
            return {"error": "PyAutoGUI не установлен. Установите: pip install pyautogui"}
        try:
            pyautogui.hotkey(*keys)
            return {"status": "success", "keys": keys}
        except Exception as e:
            logger.error(f"❌ Ошибка нажатия горячих клавиш: {str(e)}")
            return {"error": f"Ошибка нажатия горячих клавиш: {str(e)}"}

    def get_screen_resolution(self) -> Dict[str, Any]:
        """Получает разрешение экрана"""
        try:
            import pyautogui
        except ImportError:
            return {"error": "PyAutoGUI не установлен. Установите: pip install pyautogui"}
        try:
            width, height = pyautogui.size()
            return {"status": "success", "width": width, "height": height, "resolution": f"{width}x{height}"}
        except Exception as e:
            logger.error(f"❌ Ошибка получения разрешения экрана: {str(e)}")
            return {"error": f"Ошибка получения разрешения экрана: {str(e)}"}

    def get_mouse_position(self) -> Dict[str, Any]:
        """Получает позицию мыши"""
        try:
            import pyautogui
        except ImportError:
            return {"error": "PyAutoGUI не установлен. Установите: pip install pyautogui"}
        try:
            x, y = pyautogui.position()
            return {"status": "success", "x": x, "y": y, "coordinates": f"({x}, {y})"}
        except Exception as e:
            logger.error(f"❌ Ошибка получения позиции мыши: {str(e)}")
            return {"error": f"Ошибка получения позиции мыши: {str(e)}"}

    def get_active_window_info(self) -> Dict[str, Any]:
        """Получает информацию об активном окне"""
        try:
            powershell_command = """
            Add-Type @"
            using System;
            using System.Runtime.InteropServices;
            public class WindowInfo {
                [DllImport("user32.dll")]
                public static extern IntPtr GetForegroundWindow();
                [DllImport("user32.dll")]
                public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
                [DllImport("user32.dll")]
                public static extern int GetWindowTextLength(IntPtr hWnd);
            }
            "@
            $window = [WindowInfo]::GetForegroundWindow()
            $length = [WindowInfo]::GetWindowTextLength($window)
            $stringBuilder = New-Object System.Text.StringBuilder($length + 1)
            [WindowInfo]::GetWindowText($window, $stringBuilder, $stringBuilder.Capacity) | Out-Null
            $title = $stringBuilder.ToString()
            Write-Output "Title:$title"
            Write-Output "Handle:$window"
            """
            result = subprocess.run(
                ["powershell", "-Command", powershell_command],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10
            )
            if result.returncode == 0:
                title = "Неизвестно"
                handle = "Неизвестно"
                stdout = result.stdout or ""
                for line in stdout.splitlines():
                    if line.startswith("Title:"):
                        title = line[6:].strip()
                    elif line.startswith("Handle:"):
                        handle = line[7:].strip()
                return {"status": "success", "title": title, "handle": handle, "timestamp": datetime.now().isoformat()}
            return {"error": "Не удалось получить информацию об активном окне"}
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации об активном окне: {str(e)}")
            return {"error": f"Ошибка получения информации об активном окне: {str(e)}"}

    def list_windows(self) -> Dict[str, Any]:
        """Получает список окон"""
        try:
            powershell_command = """
            Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object Id, ProcessName, MainWindowTitle | ConvertTo-Json
            """
            result = subprocess.run(
                ["powershell", "-Command", powershell_command],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=15
            )
            stdout = (result.stdout or "").strip()
            if result.returncode == 0 and stdout:
                import json as _json
                try:
                    windows = _json.loads(stdout)
                except Exception:
                    # Если JSON некорректен, возвращаем частичный результат
                    return {"status": "partial", "raw": stdout}
                if not isinstance(windows, list):
                    windows = [windows]
                return {"status": "success", "windows": windows, "count": len(windows)}
            return {"error": "Не удалось получить список окон"}
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка окон: {str(e)}")
            return {"error": f"Ошибка получения списка окон: {str(e)}"}

    def focus_window(self, app_name: Optional[str] = None, maximize: bool = True) -> Dict[str, Any]:
        """Переводит указанное окно (или активное) на передний план."""
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        EnumWindows = user32.EnumWindows
        EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), ctypes.c_void_p]
        EnumWindows.restype = ctypes.c_bool

        IsWindowVisible = user32.IsWindowVisible
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        GetWindowTextW = user32.GetWindowTextW
        SetForegroundWindow = user32.SetForegroundWindow
        ShowWindow = user32.ShowWindow

        SW_RESTORE = 9
        SW_SHOW = 5

        target_hwnd = None
        target_process = (app_name or "").strip().lower() if app_name else None

        def _enum_proc(hwnd, lParam):
            nonlocal target_hwnd
            if not IsWindowVisible(hwnd):
                return True
            length = GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if not title:
                return True
            if not target_process:
                target_hwnd = hwnd
                return False
            try:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                proc = psutil.Process(pid.value)
                name = proc.name().lower()
            except Exception:
                name = ""
            if target_process and (target_process in name or target_process in title.lower()):
                target_hwnd = hwnd
                return False
            return True

        if target_hwnd is None:
            if target_process in self.enum_windows_cache:
                target_hwnd = self.enum_windows_cache[target_process]
            else:
                EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(_enum_proc), 0)
                self.enum_windows_cache[target_process] = target_hwnd

        if not target_hwnd:
            return {"status": "error", "error": "Окно не найдено"}

        if maximize:
            ShowWindow(target_hwnd, SW_RESTORE)
        else:
            ShowWindow(target_hwnd, SW_SHOW)

        if not SetForegroundWindow(target_hwnd):
            return {"status": "error", "error": "Не удалось сфокусировать окно"}

        return {"status": "success", "message": "Окно сфокусировано"}
        
        
        
        
        
        
        
        
        
        


# Создаём глобальный экземпляр
cmd_manager = WindowsCommandManager()


# Экспортируемые функции
def execute_system_command(command: str, working_dir: Optional[str] = None) -> Dict[str, Any]:
    """Выполняет системную команду"""
    return cmd_manager.execute_command(command, working_dir)


def open_application(app_name: str, args: str = "") -> Dict[str, Any]:
    """Открывает приложение"""
    return cmd_manager.open_application(app_name, args)


def close_application(app_name: str, force: bool = True) -> Dict[str, Any]:
    """Закрывает приложение"""
    return cmd_manager.close_application(app_name, force)


def list_processes(name_filter: Optional[str] = None) -> Dict[str, Any]:
    """Список процессов"""
    return cmd_manager.list_processes(name_filter)


def get_system_info() -> Dict[str, Any]:
    """Информация о системе"""
    return cmd_manager.get_system_info()


def open_camera() -> Dict[str, Any]:
    """Открывает камеру"""
    return cmd_manager.open_camera()


def take_photo(output_path: Optional[str] = None) -> Dict[str, Any]:
    """Делает фото"""
    return cmd_manager.take_photo(output_path)


def start_voice_recording() -> Dict[str, Any]:
    """Запускает запись звука"""
    return cmd_manager.start_voice_recording()

def stop_voice_recording() -> Dict[str, Any]:
    """Останавливает запись звука"""
    return cmd_manager.stop_voice_recording()


def schedule_task(action: str, **kwargs) -> Dict[str, Any]:
    """Планирует задачу"""
    return cmd_manager.schedule_task(action, **kwargs)

def schedule_recurring_task(action: str, **kwargs) -> Dict[str, Any]:
    return cmd_manager.schedule_recurring_task(action, **kwargs)


def list_scheduled_tasks() -> Dict[str, Any]:
    """Список задач"""
    return cmd_manager.list_scheduled_tasks()


def cancel_scheduled_task(task_id: int) -> Dict[str, Any]:
    """Отменяет задачу"""
    return cmd_manager.cancel_scheduled_task(task_id)

def minimize_all_windows() -> Dict[str, Any]:
    return cmd_manager.minimize_all_windows()

def find_executable(app_name: str, use_cache: bool = True, search_all_drives: bool = False) -> Dict[str, Any]:
    return cmd_manager.find_executable(app_name, use_cache, search_all_drives)

def open_application_advanced(app_name: str, args: str = "", search_all_drives: bool = False) -> Dict[str, Any]:
    return cmd_manager.open_application_advanced(app_name, args, search_all_drives)

def locate_app_icon_on_desktop(app_name: str) -> Dict[str, Any]:
    return cmd_manager.locate_app_icon_on_desktop(app_name)

def focus_window(app_name: Optional[str] = None, maximize: bool = True) -> Dict[str, Any]:
    """Сфокусировать и развернуть окно приложения (если app_name указан)"""
    return cmd_manager.focus_window(app_name, maximize)

def take_desktop_screenshot(filename: str, directory: Optional[str] = None) -> Dict[str, Any]:
    """Скриншот рабочего стола"""
    return cmd_manager.take_desktop_screenshot(filename, directory)

def click_at_coordinates(x: int, y: int, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
    """Клик по координатам"""
    return cmd_manager.click_at_coordinates(x, y, button, clicks)

def move_mouse(x: int, y: int, duration: float = 0.5) -> Dict[str, Any]:
    """Перемещение мыши"""
    return cmd_manager.move_mouse(x, y, duration)

def type_text(text: str, interval: float = 0.1) -> Dict[str, Any]:
    """Ввод текста"""
    return cmd_manager.type_text(text, interval)

def press_key(key: str, presses: int = 1) -> Dict[str, Any]:
    """Нажатие клавиши"""
    return cmd_manager.press_key(key, presses)

def press_hotkey(keys: List[str]) -> Dict[str, Any]:
    return cmd_manager.press_hotkey(keys)

def get_screen_resolution() -> Dict[str, Any]:
    """Разрешение экрана"""
    return cmd_manager.get_screen_resolution()

def get_mouse_position() -> Dict[str, Any]:
    """Позиция мыши"""
    return cmd_manager.get_mouse_position()

def get_active_window_info() -> Dict[str, Any]:
    """Информация об активном окне"""
    return cmd_manager.get_active_window_info()

def list_windows() -> Dict[str, Any]:
    """Список окон"""
    return cmd_manager.list_windows()