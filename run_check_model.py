# run-check-model.py____________________________________________________________________________________________________

"""
Проверка и инициализация модели Ollama
Улучшенная версия с комплексным тестированием возможностей
"""
import requests
import json
import time
import os
import base64
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import config

logger = config.logger


class OllamaManager:
    """Управление Ollama моделью с расширенным тестированием"""
    
    def __init__(self):
        self.host = config.OLLAMA_HOST
        self.model = config.MODEL
        self.timeout = config.REQUEST_TIMEOUT
        self.is_available = False
        self.capabilities = {
            "text_generation": False,
            "json_generation": False,
            "structured_planning": False,
            "vision": False,
            "tool_calling": False
        }
        
    def check_connection(self) -> Tuple[bool, str]:
        """Проверяет подключение к Ollama с детальной диагностикой"""
        logger.info("🔍 Проверка подключения к Ollama...")
        
        try:
            # Проверяем базовый эндпоинт
            response = requests.get(f"{self.host}/api/tags", timeout=10)
            response.raise_for_status()
            
            # Проверяем версию API
            version_response = requests.get(f"{self.host}/api/version", timeout=5)
            if version_response.status_code == 200:
                version_info = version_response.json()
                logger.info(f"📡 Ollama версия: {version_info.get('version', 'неизвестно')}")
            
            logger.info("✅ Ollama сервер доступен")
            self.is_available = True
            return True, "Ollama сервер доступен"
            
        except requests.exceptions.ConnectionError:
            error_msg = "Не удалось подключиться к Ollama. Убедитесь, что сервер запущен."
            logger.error(f"❌ {error_msg}")
            logger.info("💡 Запустите Ollama: ollama serve")
            return False, error_msg
            
        except requests.exceptions.Timeout:
            error_msg = f"Таймаут подключения к Ollama ({self.timeout}с)"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Ошибка подключения к Ollama: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
    
    def check_model(self) -> Tuple[bool, List[str]]:
        """Проверяет наличие модели и возвращает список доступных"""
        logger.info(f"🔍 Проверка наличия модели: {self.model}")
        
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=10)
            response.raise_for_status()
            
            data = response.json()
            models = data.get("models", [])
            
            model_names = [m.get("name", "") for m in models]
            model_details = [f"{m.get('name', '')} ({m.get('size', '')})" for m in models]
            
            if self.model in model_names:
                logger.info(f"✅ Модель {self.model} установлена")
                return True, model_details
            else:
                logger.warning(f"⚠️ Модель {self.model} не найдена")
                logger.info(f"💡 Установленные модели: {', '.join(model_names)}")
                logger.info(f"💡 Установите модель: ollama pull {self.model}")
                return False, model_details
                
        except Exception as e:
            logger.error(f"❌ Ошибка проверки модели: {str(e)}")
            return False, []
    
    def test_basic_generation(self) -> Tuple[bool, str]:
        """Тестирует базовую генерацию текста с осмысленным промптом"""
        logger.info("🧪 Тестирование базовой генерации...")
        
        test_prompt = """Ты - AI ассистент для автоматизации задач на Windows. 
Пользователь попросит тебя выполнять различные задачи через инструменты.
Ответь кратко: готов ли ты к работе и в двух предложениях опиши свои основные возможности."""

        try:
            response = self.call_ollama(test_prompt, fast=True)
            
            if "ERROR" in response:
                logger.error(f"❌ Ошибка генерации: {response}")
                return False, response
            
            # Проверяем что ответ осмысленный (не пустой и не ошибка)
            if len(response.strip()) < 10:
                logger.error("❌ Ответ слишком короткий, вероятно проблема с генерацией")
                return False, "Ответ слишком короткий"
            
            logger.info(f"✅ Базовая генерация работает! Ответ: {response[:150]}...")
            return True, response
            
        except Exception as e:
            error_msg = f"Ошибка тестирования генерации: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
    
    def test_json_generation(self) -> Tuple[bool, Dict[str, Any]]:
        """Тестирует генерацию JSON - критично для работы агента"""
        logger.info("📊 Тестирование генерации JSON...")
        
        test_prompt = """Создай JSON план для задачи "найти информацию о погоде в Москве".
Верни JSON в формате:
{
  "plan": [
    {
      "step": 1,
      "description": "описание шага",
      "tool": "имя_инструмента", 
      "args": {"параметр": "значение"}
    }
  ]
}"""

        try:
            response = self.call_ollama(test_prompt, format="json", fast=True)
            
            if "ERROR" in response:
                logger.error(f"❌ Ошибка JSON генерации: {response}")
                return False, {"error": response}
            
            # Пытаемся распарсить JSON
            try:
                json_data = json.loads(response)
                
                # Проверяем структуру
                if isinstance(json_data, dict) and "plan" in json_data:
                    if isinstance(json_data["plan"], list) and len(json_data["plan"]) > 0:
                        logger.info("✅ JSON генерация работает! Получен валидный план")
                        self.capabilities["json_generation"] = True
                        self.capabilities["structured_planning"] = True
                        return True, json_data
                    else:
                        logger.warning("⚠️ JSON сгенерирован, но структура плана неверная")
                        return False, json_data
                else:
                    logger.warning("⚠️ JSON сгенерирован, но отсутствует поле 'plan'")
                    return False, json_data
                    
            except json.JSONDecodeError as e:
                logger.error(f"❌ Сгенерирован невалидный JSON: {e}")
                logger.debug(f"Ответ модели: {response}")
                return False, {"error": f"Невалидный JSON: {e}", "response": response}
                
        except Exception as e:
            error_msg = f"Ошибка тестирования JSON генерации: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, {"error": error_msg}
    
    def call_ollama(self, prompt: str, tools: Optional[list] = None,
                    max_retries: int = 2, images: Optional[list] = None, fast: bool = False,
                    options: Optional[Dict[str, Any]] = None, format: Optional[str] = None) -> str:
        """Вызывает Ollama API с ограничением длины ответа и авто-стопами для yes/no и X,Y."""
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"🧠 Попытка {attempt + 1}: запрос к модели {self.model}...")
                data: Dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
                if format:
                    data["format"] = format
                base_options: Dict[str, Any] = {"temperature": 0.2, "num_ctx": 2048, "num_predict": 192, "top_k": 20, "top_p": 0.7}
                if fast:
                    try:
                        from config import FAST_TEXT_CONFIG
                        base_options.update(FAST_TEXT_CONFIG)
                    except Exception:
                        pass
                    base_options["num_predict"] = min(128, int(base_options.get("num_predict", 128)))
                if options:
                    try:
                        base_options.update(options)
                    except Exception:
                        pass
                low_prompt = (prompt or "").lower()
                stops: List[str] = []
                if ("ответь кратко: yes" in low_prompt) or ("ответь кратко: no" in low_prompt) or ("верни только: x,y" in low_prompt) or ("только: x,y" in low_prompt):
                    base_options["num_predict"] = min(16, int(base_options.get("num_predict", 64)))
                    stops.extend(["\n\n", "\n-", "Ответ:"])
                if (format == "json") or ("верни json" in low_prompt) or ("return json" in low_prompt):
                    data["format"] = "json"
                    base_options["num_predict"] = min(256, int(base_options.get("num_predict", 256)))
                if stops:
                    base_options["stop"] = stops
                data["options"] = base_options
                if tools:
                    data["tools"] = tools
                if images:
                    data["images"] = images
                start_time = time.time()
                response = requests.post(f"{self.host}/api/generate", json=data, timeout=self.timeout)
                response_time = time.time() - start_time
                logger.info(f"⏱️ Время ответа: {response_time:.2f}с")
                if response.status_code != 200:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    logger.error(f"❌ Ошибка API: {error_msg}")
                    if attempt < max_retries:
                        time.sleep(2)
                        continue
                    return f"ERROR: {error_msg}"
                if not response.content:
                    if attempt < max_retries:
                        time.sleep(1)
                        continue
                    return "ERROR: Empty response"
                response_data = response.json()
                result = ""
                if isinstance(response_data, dict):
                    result = str(response_data.get("response", ""))
                elif isinstance(response_data, list):
                    parts: List[str] = []
                    for item in response_data:
                        if isinstance(item, dict) and "response" in item:
                            parts.append(str(item.get("response", "")))
                    result = "".join(parts) if parts else json.dumps(response_data, ensure_ascii=False)
                else:
                    result = str(response_data)
                if (not result or not result.strip()) and isinstance(response_data, dict):
                    thinking = response_data.get("thinking", "")
                    if thinking:
                        try:
                            thinking_obj = json.loads(thinking) if isinstance(thinking, str) else thinking
                            if isinstance(thinking_obj, dict):
                                if isinstance(thinking_obj.get("plan"), list):
                                    result = json.dumps(thinking_obj["plan"], ensure_ascii=False)
                                elif isinstance(thinking_obj.get("steps"), list):
                                    result = json.dumps(thinking_obj["steps"], ensure_ascii=False)
                                else:
                                    result = json.dumps(thinking_obj, ensure_ascii=False)
                            elif isinstance(thinking_obj, list):
                                result = json.dumps(thinking_obj, ensure_ascii=False)
                            else:
                                result = str(thinking)
                        except Exception:
                            result = str(thinking)
                if not result or not result.strip():
                    try:
                        result = json.dumps(response_data, ensure_ascii=False)
                    except Exception:
                        result = str(response_data)
                if isinstance(result, (dict, list)):
                    try:
                        result = json.dumps(result, ensure_ascii=False)
                    except Exception:
                        result = str(result)
                logger.info(f"✅ Ответ получен: {len(result)} символов")
                return result
            except requests.exceptions.Timeout:
                logger.warning(f"⚠️ Таймаут попытки {attempt + 1}")
                if attempt < max_retries:
                    time.sleep(3)
                    continue
                logger.error("❌ Все попытки завершились таймаутом")
                return "ERROR: Таймаут при запросе к Ollama"
            except Exception as e:
                logger.error(f"❌ Ошибка запроса к Ollama: {str(e)}")
                if attempt < max_retries:
                    time.sleep(2)
                    continue
                return f"ERROR: Ошибка подключения к Ollama: {str(e)}"
        return "ERROR: Не удалось получить ответ от модели"

    def analyze_image(self, image_path: str, question: str,
                      save_to_file: Optional[str] = None) -> Dict[str, Any]:
        """Анализирует изображение с помощью LLM (компактные ответы по умолчанию)."""
        try:
            if not os.path.exists(image_path):
                return {"error": f"Файл не найден: {image_path}"}
            with open(image_path, "rb") as img_file:
                image_data = base64.b64encode(img_file.read()).decode('utf-8')
            data: Dict[str, Any] = {
                "model": self.model,
                "prompt": question,
                "stream": False,
                "images": [image_data],
                "options": {"temperature": 0.1, "num_ctx": 2048, "num_predict": 200}
            }
            low_q = (question or "").lower()
            if ("ответь кратко: yes" in low_q) or ("ответь кратко: no" in low_q):
                data["options"]["num_predict"] = 8
                data["options"]["stop"] = ["\n", " "]
            if ("верни только: x,y" in low_q) or ("только: x,y" in low_q):
                data["options"]["num_predict"] = 12
                data["options"]["stop"] = ["\n", " "]
            logger.info(f"🖼️ Анализируем изображение: {image_path}")
            response = requests.post(f"{self.host}/api/generate", json=data, timeout=self.timeout)
            if response.status_code == 200:
                result = response.json().get("response", "")
                logger.info("✅ Анализ изображения завершен")
                return {"status": "success", "analysis": result, "image_path": image_path, "question": question}
            else:
                error_msg = f"Ошибка API: {response.status_code}"
                logger.error(f"❌ {error_msg}")
                return {"error": error_msg}
        except Exception as e:
            logger.error(f"❌ Ошибка анализа изображения: {e}")
            return {"error": f"Ошибка анализа изображения: {e}"}
    
    def test_vision_capabilities(self) -> Tuple[bool, str]:
        """Тестирует мультимодальные возможности"""
        logger.info("🖼️ Проверка мультимодальных возможностей...")
        
        # Проверяем по названию модели
        model_lower = self.model.lower()
        vision_keywords = ["vl", "vision", "llava", "bakllava", "minicpm-v"]
        
        has_vision_in_name = any(keyword in model_lower for keyword in vision_keywords)
        
        if has_vision_in_name:
            logger.info("✅ Модель заявлена как поддерживающая анализ изображений")
            self.capabilities["vision"] = True
            
            # Проверяем созданием тестового изображения
            test_result, test_message = self._test_vision_with_image()
            return test_result, test_message or "Тест vision завершен"
        else:
            warning_msg = "Модель может не поддерживать анализ изображений"
            logger.warning(f"⚠️ {warning_msg}")
            logger.info(f"💡 Рекомендуется использовать модель с поддержкой vision (например, qwen2-vl, llava, bakllava)")
            return False, warning_msg
    
    def _test_vision_with_image(self) -> Tuple[bool, str]:
        """Создает тестовое изображение и проверяет анализ"""
        try:
            # Создаем простой текстовый файл как изображение (временно)
            test_image_path = config.TEMP_DIR / "vision_test.png"
            
            # Пытаемся создать простейшее изображение через PIL или использовать существующее
            try:
                from PIL import Image, ImageDraw, ImageFont
                
                # Создаем простое изображение с текстом
                img = Image.new('RGB', (200, 100), color='white')
                d = ImageDraw.Draw(img)
                
                # Пытаемся использовать базовый шрифт
                try:
                    font = ImageFont.load_default()
                    d.text((10, 10), "Vision Test", fill='black', font=font)
                except:
                    d.text((10, 10), "Vision Test", fill='black')
                
                img.save(test_image_path)
                logger.info(f"📸 Создано тестовое изображение: {test_image_path}")
                
            except ImportError:
                # Если PIL нет, используем существующий файл или пропускаем тест
                if not test_image_path.exists():
                    logger.warning("⚠️ Не удалось создать тестовое изображение (требуется PIL)")
                    return False, "Требуется установка PIL для тестирования vision"
                else:
                    logger.info("📸 Используется существующее тестовое изображение")
            
            # Тестируем анализ изображения
            question = "Что написано на этом изображении? Ответь кратко."
            result = self.analyze_image(str(test_image_path), question)
            
            if result.get("error"):
                error_msg = f"Vision не работает: {result.get('error')}"
                logger.error(f"❌ {error_msg}")
                return False, error_msg
            else:
                analysis = result.get('analysis', '')
                if analysis:
                    logger.info(f"✅ Vision работает! Анализ: {analysis[:100]}...")
                    return True, analysis
                else:
                    logger.warning("⚠️ Vision вернул пустой анализ")
                    return False, "Пустой анализ изображения"
                
        except Exception as e:
            error_msg = f"Ошибка тестирования vision: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
    
    def test_tool_calling_capabilities(self) -> Tuple[bool, str]:
        """Тестирует способность модели работать с инструментами"""
        logger.info("🔧 Тестирование работы с инструментами...")
        
        test_prompt = """Пользователь просит: "Найди информацию о Python на официальном сайте"

Доступные инструменты:
- search_web: поиск в интернете
- navigate_to_url: переход по URL
- extract_text_from_page: извлечение текста со страницы

Создай план из 2-3 шагов используя эти инструменты. Верни JSON массив с заголовком [plan..]"""

        try:
            response = self.call_ollama(test_prompt, format="json", fast=True)
            
            if "ERROR" in response:
                return False, response
            
            # Проверяем что ответ содержит инструменты
            try:
                plan = json.loads(response)
                if isinstance(plan, list):
                    tools_used = [step.get('tool', '') for step in plan if isinstance(step, dict)]
                    valid_tools = [tool for tool in tools_used if tool]
                    
                    if valid_tools:
                        logger.info(f"✅ Модель может работать с инструментами: {', '.join(valid_tools)}")
                        self.capabilities["tool_calling"] = True
                        return True, f"Использованы инструменты: {', '.join(valid_tools)}"
                    else:
                        logger.warning("⚠️ Модель создала план, но не использовала инструменты")
                        return False, "План не содержит инструменты"
                else:
                    logger.warning("⚠️ Модель не вернула массив шагов")
                    return False, "Ответ не является массивом шагов"
                    
            except json.JSONDecodeError:
                logger.warning("⚠️ Модель не вернула валидный JSON для инструментов")
                return False, "Невалидный JSON ответ"
                
        except Exception as e:
            error_msg = f"Ошибка тестирования инструментов: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
    
    def comprehensive_test(self) -> Dict[str, Any]:
        """Выполняет комплексное тестирование всех возможностей"""
        logger.info("🎯 Запуск комплексного тестирования модели...")
        
        results = {
            "model": self.model,
            "host": self.host,
            "overall_status": "FAILED",
            "capabilities": self.capabilities.copy(),
            "details": {}
        }
        
        # 1. Проверка подключения
        connection_ok, connection_msg = self.check_connection()
        results["details"]["connection"] = {
            "status": "OK" if connection_ok else "FAILED",
            "message": connection_msg
        }
        
        if not connection_ok:
            results["overall_status"] = "FAILED"
            return results
        
        # 2. Проверка модели
        model_ok, available_models = self.check_model()
        results["details"]["model_availability"] = {
            "status": "OK" if model_ok else "FAILED", 
            "message": f"Модель {'найдена' if model_ok else 'не найдена'}",
            "available_models": available_models
        }
        
        if not model_ok:
            results["overall_status"] = "FAILED"
            return results
        
        # 3. Тестирование базовой генерации
        basic_ok, basic_msg = self.test_basic_generation()
        results["details"]["basic_generation"] = {
            "status": "OK" if basic_ok else "FAILED",
            "message": basic_msg[:500] if basic_ok and basic_msg else basic_msg
        }
        results["capabilities"]["text_generation"] = basic_ok
        
        if not basic_ok:
            results["overall_status"] = "FAILED"
            return results
        
        # 4. Тестирование JSON генерации
        json_ok, json_data = self.test_json_generation()
        results["details"]["json_generation"] = {
            "status": "OK" if json_ok else "FAILED",
            "message": "Успешная генерация JSON" if json_ok else str(json_data.get('error', json_data))
        }
        
        # 5. Тестирование инструментов
        tools_ok, tools_msg = self.test_tool_calling_capabilities()
        results["details"]["tool_calling"] = {
            "status": "OK" if tools_ok else "WARNING",
            "message": tools_msg
        }
        
        # 6. Тестирование vision
        vision_ok, vision_msg = self.test_vision_capabilities()
        results["details"]["vision"] = {
            "status": "OK" if vision_ok else "WARNING", 
            "message": vision_msg[:500] if vision_ok and vision_msg else vision_msg
        }

        # Определяем общий статус
        critical_ok = connection_ok and model_ok and basic_ok
        if critical_ok and (json_ok or tools_ok):
            results["overall_status"] = "READY"
        elif critical_ok:
            results["overall_status"] = "LIMITED"
        else:
            results["overall_status"] = "FAILED"
        return results

    def initialize(self) -> Tuple[bool, Dict[str, Any]]:
        """Инициализация Ollama: выполняет комплексный тест и возвращает (ok, results)."""
        try:
            results = self.comprehensive_test()
            ok = str(results.get("overall_status", "")).upper() in {"READY", "LIMITED"}
            return ok, results
        except Exception as e:
            return False, {"overall_status": "FAILED", "details": {"init": {"status": "FAILED", "message": str(e)}}}


# Глобальный менеджер и экспортируемые обертки
ollama_manager = OllamaManager()

def check_ollama() -> bool:
    success, _ = ollama_manager.initialize()
    return success

def comprehensive_check_ollama() -> Tuple[bool, Dict[str, Any]]:
    return ollama_manager.initialize()

def call_ollama(prompt: str, tools: Optional[list] = None,
               images: Optional[list] = None, fast: bool = False,
               options: Optional[Dict[str, Any]] = None, format: Optional[str] = None) -> str:
    return ollama_manager.call_ollama(prompt, tools, images=images, fast=fast, options=options, format=format)

def analyze_image(image_path: str, question: str,
                 save_to_file: Optional[str] = None) -> Dict[str, Any]:
    return ollama_manager.analyze_image(image_path, question, save_to_file)

def get_model_capabilities() -> Dict[str, bool]:
    return ollama_manager.capabilities


if __name__ == "__main__":
    # Standalone запуск для проверки
    print("\n🔍 КОМПЛЕКСНАЯ ПРОВЕРКА OLLAMA\n")
    
    success, results = comprehensive_check_ollama()
    
    if success:
        status = results["overall_status"]
        if status == "READY":
            print("\n🎉 Все проверки пройдены! Модель готова к работе.")
        elif status == "LIMITED":
            print("\n⚠️  Модель работает с ограничениями. Проверьте предупреждения выше.")
        
        print("\n📊 Детали возможностей:")
        for capability, enabled in results["capabilities"].items():
            status = "✅ Доступно" if enabled else "❌ Недоступно"
            print(f"   {capability}: {status}")
            
        print("\n💡 Ollama готова к работе с агентом\n")
    else:
        print("\n❌ Обнаружены критические проблемы!")
        print("💡 Исправьте ошибки перед запуском агента\n")
        
        # Показываем детали ошибок
        for test_name, detail in results["details"].items():
            if detail["status"] == "FAILED":
                print(f"   🔴 {test_name}: {detail['message']}")