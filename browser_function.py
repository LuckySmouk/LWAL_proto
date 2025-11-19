# browser_function.py (улучшенная версия)
# ====================================================================

import time
import random
import re
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

from playwright.sync_api import (
    sync_playwright, 
    Playwright, 
    Browser, 
    BrowserContext, 
    Page, 
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError
)
import config

logger = config.logger

# Глобальная страница браузера (Playwright)
page: Optional[Page] = None


class BrowserManager:
    """
    Улучшенный менеджер браузера с:
    - Лучшей обработкой капчи
    - Подключением к существующим сессиям Chrome/Edge
    - Стелс-режимом для обхода детекции автоматизации
    - Улучшенной обработкой ошибок
    """
    
    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.session_active = False
        self.attached_over_cdp = False
        self.launched_by_us = False
        self.stealth_enabled = False
        
    def _cleanup_session(self):
        """Безопасная очистка предыдущей сессии"""
        try:
            if self.page:
                try:
                    self.page.close()
                except Exception:
                    pass
            if self.context:
                try:
                    self.context.close()
                except Exception:
                    pass
            # Не закрываем браузер если подключились к существующему
            if self.browser and self.launched_by_us:
                try:
                    self.browser.close()
                except Exception:
                    pass
            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception:
                    pass
        finally:
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None
            self.session_active = False
            self.attached_over_cdp = False
            self.launched_by_us = False
        
    def _apply_stealth(self, context: BrowserContext):
        """Применение стелс-настроек для обхода детекции автоматизации"""
        try:
            # Скрипт для маскировки автоматизации
            stealth_js = """
            // Переопределяем webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Маскируем chrome объект
            window.chrome = {
                runtime: {}
            };
            
            // Переопределяем permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            
            // Маскируем плагины
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Маскируем языки
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ru-RU', 'ru', 'en-US', 'en']
            });
            """
            
            context.add_init_script(stealth_js)
            self.stealth_enabled = True
            logger.info("✅ Стелс-режим активирован")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось активировать стелс-режим: {e}")
    
    def _find_chrome_executable(self) -> Optional[str]:
        """Поиск установленного Chrome/Edge для CDP подключения"""
        possible_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        
        for path in possible_paths:
            if Path(path).exists():
                logger.info(f"🔍 Найден браузер: {path}")
                return path
        
        return None
    
    def _get_cdp_endpoints(self) -> List[str]:
        """Получение доступных CDP endpoints"""
        debug_port = config.BROWSER_CONFIG.get('debug_port', 9222)
        
        endpoints = []
        
        # Основной endpoint
        if config.BROWSER_CONFIG.get('cdp_url'):
            endpoints.append(config.BROWSER_CONFIG.get('cdp_url'))
        else:
            endpoints.append(f"http://localhost:{debug_port}")
        
        # Дополнительные порты для проверки
        for port in [9222, 9223, 9224]:
            endpoint = f"http://localhost:{port}"
            if endpoint not in endpoints:
                endpoints.append(endpoint)
        
        return endpoints
    
    def initialize_browser(
        self, 
        headless: Optional[bool] = None, 
        use_existing: Optional[bool] = None, 
        cdp_url: Optional[str] = None, 
        debug_port: Optional[int] = None,
        enable_stealth: bool = True
    ) -> bool:
        """
        Инициализация браузера с улучшенной обработкой подключения
        
        Args:
            headless: Запуск в headless режиме
            use_existing: Попытка подключиться к существующему браузеру
            cdp_url: URL для CDP подключения
            debug_port: Порт для remote debugging
            enable_stealth: Включить стелс-режим
        """
        global page
        
        # Закрываем предыдущую сессию
        self._cleanup_session()
        
        logger.info("🚀 Инициализация браузера...")
        
        # Параметры из конфига
        if headless is None:
            headless = config.BROWSER_CONFIG.get('headless', False)
        if use_existing is None:
            use_existing = bool(config.BROWSER_CONFIG.get('use_existing', False))
        
        # Парсим размер окна
        width, height = 1280, 720
        try:
            win_size = config.BROWSER_CONFIG.get('window_size', '1280,720')
            parts = [p.strip() for p in str(win_size).split(',')]
            if len(parts) == 2:
                width = int(parts[0])
                height = int(parts[1])
        except Exception:
            pass
        
        user_agent = config.BROWSER_CONFIG.get(
            'user_agent', 
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        user_data_dir = config.BROWSER_CONFIG.get('user_data_dir')
        
        try:
            self.playwright = sync_playwright().start()
            chromium = self.playwright.chromium
            
            # Попытка подключения к существующему браузеру
            if use_existing:
                logger.info("🔗 Попытка подключения к существующему браузеру...")
                
                # Получаем список endpoints для проверки
                endpoints = self._get_cdp_endpoints()
                if cdp_url:
                    endpoints.insert(0, cdp_url)
                
                # Пробуем подключиться к каждому endpoint
                for endpoint in endpoints:
                    try:
                        logger.info(f"🔌 Проверка endpoint: {endpoint}")
                        self.browser = chromium.connect_over_cdp(endpoint, timeout=5000)
                        self.attached_over_cdp = True
                        self.launched_by_us = False
                        
                        # Получаем существующий контекст или создаем новый
                        if self.browser.contexts:
                            self.context = self.browser.contexts[0]
                            logger.info("✅ Использован существующий контекст")
                        else:
                            self.context = self.browser.new_context(
                                viewport={'width': width, 'height': height},
                                user_agent=user_agent
                            )
                            logger.info("✅ Создан новый контекст")
                        
                        # Получаем существующую страницу или создаем новую
                        if self.context.pages:
                            self.page = self.context.pages[0]
                            logger.info(f"✅ Использована существующая вкладка: {self.page.url}")
                        else:
                            self.page = self.context.new_page()
                            logger.info("✅ Создана новая вкладка")
                        
                        # Применяем стелс-режим если нужно
                        if enable_stealth and not self.attached_over_cdp:
                            self._apply_stealth(self.context)
                        
                        logger.info(f"✅ Успешно подключено к браузеру: {endpoint}")
                        break
                        
                    except PlaywrightTimeoutError:
                        logger.debug(f"⏱️ Таймаут подключения к {endpoint}")
                        continue
                    except PlaywrightError as e:
                        logger.debug(f"❌ Ошибка подключения к {endpoint}: {e}")
                        continue
                    except Exception as e:
                        logger.debug(f"❌ Неожиданная ошибка при подключении к {endpoint}: {e}")
                        continue
                
                # Если не удалось подключиться ни к одному endpoint
                if not self.page:
                    logger.info("ℹ️ Не удалось подключиться к существующему браузеру, запускаем новый...")
            
            # Запуск нового браузера если не подключились к существующему
            if not self.page:
                launch_args = [
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    f'--window-size={width},{height}'
                ]
                
                if user_data_dir:
                    # Persistent context с профилем пользователя
                    logger.info(f"📁 Запуск с профилем: {user_data_dir}")
                    self.context = chromium.launch_persistent_context(
                        user_data_dir=str(user_data_dir),
                        headless=headless,
                        viewport={'width': width, 'height': height},
                        user_agent=user_agent,
                        args=launch_args,
                        ignore_default_args=['--enable-automation']
                    )
                    self.browser = self.context.browser
                    self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
                else:
                    # Обычный запуск
                    logger.info("🆕 Запуск нового браузера...")
                    self.browser = chromium.launch(
                        headless=headless,
                        args=launch_args
                    )
                    self.context = self.browser.new_context(
                        viewport={'width': width, 'height': height},
                        user_agent=user_agent,
                        locale='ru-RU',
                        timezone_id='Europe/Moscow'
                    )
                    self.page = self.context.new_page()
                
                # Применяем стелс-режим
                if enable_stealth:
                    self._apply_stealth(self.context)
                
                self.launched_by_us = True
                logger.info("✅ Новый браузер запущен")
            
            # Настройка таймаутов
            try:
                page_timeout = int(config.BROWSER_CONFIG.get('page_load_timeout', 30)) * 1000
                self.page.set_default_navigation_timeout(page_timeout)
                self.page.set_default_timeout(int(config.BROWSER_CONFIG.get('implicit_wait', 10)) * 1000)
            except Exception as e:
                logger.warning(f"⚠️ Ошибка установки таймаутов: {e}")
            
            # Обработчик для логирования консольных сообщений (помогает в отладке)
            def log_console(msg):
                if msg.type in ['error', 'warning']:
                    logger.debug(f"Browser console [{msg.type}]: {msg.text}")
            
            self.page.on("console", log_console)
            
            page = self.page
            self.session_active = True
            logger.info("✅ Браузер инициализирован")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации браузера: {str(e)}")
            self._cleanup_session()
            return False
    
    def close_browser(self) -> Dict[str, Any]:
        """Закрытие браузера с сохранением существующей сессии"""
        global page
        
        try:
            # Если подключились к существующему браузеру - не закрываем его
            if self.attached_over_cdp:
                logger.info("ℹ️ Отключение от существующего браузера (без закрытия)")
                # Только отключаемся, но не закрываем
                if self.playwright:
                    try:
                        self.playwright.stop()
                    except Exception:
                        pass
            else:
                # Закрываем браузер который мы запустили
                if self.page:
                    try:
                        self.page.close()
                    except Exception:
                        pass
                if self.context:
                    try:
                        self.context.close()
                    except Exception:
                        pass
                if self.browser and self.launched_by_us:
                    try:
                        self.browser.close()
                    except Exception:
                        pass
                if self.playwright:
                    try:
                        self.playwright.stop()
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"❌ Ошибка закрытия браузера: {str(e)}")
        finally:
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None
            self.session_active = False
            self.attached_over_cdp = False
            self.launched_by_us = False
            page = None
        
        logger.info("✅ Браузер закрыт")
        return {"status": "success", "message": "Браузер закрыт"}
    
    def navigate_to_url(
        self, 
        url: str, 
        wait_for_element: Optional[str] = None,
        timeout: int = 15,
        retry_on_captcha: bool = True,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Переход по URL с улучшенной обработкой капчи
        
        Args:
            url: URL для перехода
            wait_for_element: CSS селектор элемента для ожидания
            timeout: Таймаут в секундах
            retry_on_captcha: Повторять попытку при обнаружении капчи
            max_retries: Максимальное количество попыток
        """
        if not self.session_active and not self.initialize_browser():
            return {"error": "Не удалось инициализировать браузер"}
        
        assert self.page is not None
        
        # Нормализация URL
        url = self._normalize_url(url)
        if url.startswith("error:"):
            return {"error": url[6:]}
        
        logger.info(f"➡️ Переход по URL: {url}")
        
        attempt = 0
        while attempt < max_retries:
            attempt += 1
            
            try:
                # Переход на страницу
                response = self.page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                
                # Проверка статуса ответа
                if response and response.status >= 400:
                    logger.warning(f"⚠️ HTTP статус {response.status}")
                
                # Ждем загрузки body
                self.page.wait_for_selector("body", timeout=timeout * 1000, state="attached")
                
                # Дополнительное ожидание для динамического контента
                time.sleep(random.uniform(1.5, 2.5))
                
                # Проверка на капчу
                if self._detect_captcha():
                    if retry_on_captcha and attempt < max_retries:
                        logger.warning(f"🔒 Обнаружена капча (попытка {attempt}/{max_retries})")
                        handled = self._handle_captcha_advanced()
                        
                        if not handled:
                            # Увеличиваем задержку между попытками
                            delay = random.uniform(5, 10) * attempt
                            logger.info(f"⏳ Ожидание {delay:.1f} сек перед повторной попыткой...")
                            time.sleep(delay)
                            continue
                    else:
                        return {
                            "error": "Обнаружена капча, не удалось обойти",
                            "url": self.page.url,
                            "requires_manual_intervention": True
                        }
                
                # Ожидание специфичного элемента если указан
                if wait_for_element:
                    try:
                        self.page.wait_for_selector(
                            wait_for_element, 
                            timeout=timeout * 1000,
                            state="visible"
                        )
                        logger.info(f"✅ Элемент '{wait_for_element}' найден")
                    except PlaywrightTimeoutError:
                        logger.warning(f"⚠️ Элемент '{wait_for_element}' не найден за {timeout}с")
                
                # Имитация человеческого поведения
                self._simulate_human_behavior()
                
                current_url = self.page.url
                title = self.page.title()
                
                logger.info(f"✅ Успешный переход: {title}")
                
                return {
                    "status": "success",
                    "url": current_url,
                    "title": title,
                    "timestamp": datetime.now().isoformat(),
                    "attempts": attempt
                }
                
            except PlaywrightTimeoutError:
                if attempt < max_retries:
                    logger.warning(f"⏱️ Таймаут (попытка {attempt}/{max_retries}), повтор...")
                    time.sleep(random.uniform(2, 4))
                    continue
                else:
                    logger.error(f"❌ Таймаут при загрузке страницы: {url}")
                    return {"error": f"Таймаут при загрузке страницы после {max_retries} попыток"}
            
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"⚠️ Ошибка (попытка {attempt}/{max_retries}): {str(e)}")
                    time.sleep(random.uniform(2, 4))
                    continue
                else:
                    logger.error(f"❌ Ошибка перехода: {str(e)}")
                    return {"error": f"Ошибка перехода: {str(e)}"}
        
        return {"error": f"Не удалось перейти по URL после {max_retries} попыток"}
    
    def _normalize_url(self, url: Any) -> str:
        """Нормализация и валидация URL"""
        try:
            raw = url
            
            # Приведение к строке
            if not isinstance(raw, str):
                if isinstance(raw, dict):
                    raw = raw.get("url") or raw.get("link") or raw.get("href") or str(raw)
                elif isinstance(raw, list) and raw:
                    raw = raw[0]
                raw = str(raw)
            
            s = raw.strip()
            
            # Поддержка подсказки вида: "Ссылка из файла <path> (первая строка)"
            if "Ссылка из файла" in s or re.search(r'[A-Za-z]:\\', s):
                match = re.search(r"([A-Za-z]:\\[^\n\)]+\.(?:txt|csv))", s)
                if match:
                    file_path = match.group(1)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                u = line.strip()
                                if u and (u.startswith("http") or "." in u):
                                    s = u
                                    logger.info(f"📄 Прочитал URL из файла: {file_path} -> {s}")
                                    break
                    except Exception as fe:
                        return f"error:Не удалось прочитать файл ссылок: {fe}"
            
            # Добавление схемы
            if not s.startswith(("http://", "https://")):
                if s.startswith("www."):
                    s = "https://" + s
                elif "." in s and not s.startswith("/"):
                    s = "https://" + s
            
            # Базовая валидация URL
            try:
                parsed = urllib.parse.urlparse(s)
                if not parsed.scheme or not parsed.netloc:
                    return f"error:Некорректный URL: {s}"
            except Exception:
                return f"error:Некорректный URL: {s}"
            
            logger.info(f"🔧 URL нормализован: {s}")
            return s
            
        except Exception as e:
            return f"error:Ошибка нормализации URL: {e}"
    
    def _detect_captcha(self) -> bool:
        """Улучшенное обнаружение капчи и защиты"""
        if self.page is None:
            return False
        
        try:
            # Расширенный список селекторов капчи
            captcha_selectors = [
                # Google reCAPTCHA
                'iframe[src*="recaptcha"]',
                '.g-recaptcha',
                '#g-recaptcha',
                
                # hCaptcha
                'iframe[src*="hcaptcha"]',
                '.h-captcha',
                
                # Cloudflare
                '#challenge-form',
                '.cf-browser-verification',
                '#cf-wrapper',
                'div[class*="cloudflare"]',
                
                # Общие
                'div[class*="captcha"]',
                'div[id*="captcha"]',
                'form[action*="captcha"]',
                
                # Кастомные из конфига
                *config.CAPTCHA_SELECTORS
            ]
            
            # Проверка текста на странице
            try:
                body_text = self.page.locator("body").inner_text(timeout=2000)
                captcha_keywords = [
                    "verify you are human",
                    "please verify",
                    "captcha",
                    "проверка безопасности",
                    "подтвердите что вы не робот",
                    "cloudflare",
                    "security check"
                ]
                
                if any(keyword.lower() in body_text.lower() for keyword in captcha_keywords):
                    logger.debug("🔍 Обнаружены ключевые слова капчи в тексте")
                    return True
            except Exception:
                pass
            
            # Проверка селекторов
            for selector in captcha_selectors:
                try:
                    count = self.page.locator(selector).count()
                    if count > 0:
                        logger.debug(f"🔍 Обнаружена капча по селектору: {selector}")
                        return True
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            logger.debug(f"⚠️ Ошибка детекции капчи: {e}")
            return False
    
    def _handle_captcha_advanced(self) -> bool:
        """
        Продвинутая обработка капчи с несколькими стратегиями
        """
        if self.page is None:
            return False
        
        try:
            logger.info("🔓 Попытка обработки капчи...")
            
            # Стратегия 1: Ожидание (для Cloudflare challenge)
            logger.info("⏳ Стратегия 1: Ожидание автоматического решения...")
            for i in range(15):  # Ждем до 15 секунд
                time.sleep(1)
                if not self._detect_captcha():
                    logger.info("✅ Капча пройдена автоматически")
                    return True
                
                # Проверяем изменение URL (редирект после капчи)
                try:
                    current_url = self.page.url
                    if "challenge" not in current_url.lower() and "captcha" not in current_url.lower():
                        logger.info("✅ Редирект после капчи выполнен")
                        return True
                except Exception:
                    pass
            
            # Стратегия 2: Обновление страницы с задержкой
            logger.info("🔄 Стратегия 2: Обновление страницы...")
            delay = random.uniform(3, 7)
            time.sleep(delay)
            
            self.page.reload(wait_until="domcontentloaded")
            time.sleep(random.uniform(2, 4))
            
            if not self._detect_captcha():
                logger.info("✅ Капча пройдена после обновления")
                return True
            
            # Стратегия 3: Имитация активности пользователя
            logger.info("🖱️ Стратегия 3: Имитация активности...")
            try:
                # Движение мыши
                self.page.mouse.move(
                    random.randint(100, 500),
                    random.randint(100, 500)
                )
                time.sleep(random.uniform(0.5, 1.5))
                
                # Клик в случайное место
                self.page.mouse.click(
                    random.randint(200, 600),
                    random.randint(200, 400)
                )
                time.sleep(random.uniform(1, 2))
                
                # Прокрутка
                self.page.evaluate("window.scrollBy(0, Math.random() * 200);")
                time.sleep(random.uniform(1, 2))
                
                if not self._detect_captcha():
                    logger.info("✅ Капча пройдена после имитации активности")
                    return True
            except Exception as e:
                logger.debug(f"⚠️ Ошибка имитации активности: {e}")
            
            # Стратегия 4: Если подключены к пользовательской сессии - ждем решения вручную
            if self.attached_over_cdp:
                logger.warning("⏸️ Обнаружена капча в пользовательской сессии")
                logger.warning("🖐️ Пожалуйста, решите капчу вручную в браузере...")
                
                # Ждем до 60 секунд пока пользователь решит капчу
                for i in range(60):
                    time.sleep(1)
                    if not self._detect_captcha():
                        logger.info("✅ Капча решена пользователем")
                        return True
                    
                    if i % 10 == 0:
                        logger.info(f"⏳ Ожидание решения капчи... ({i}/60 сек)")
            
            logger.warning("❌ Не удалось обойти капчу")
            return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки капчи: {str(e)}")
            return False
    
    def _simulate_human_behavior(self):
        """Имитация поведения человека для снижения детекции"""
        if self.page is None:
            return
        
        try:
            # Случайная пауза
            time.sleep(random.uniform(0.5, 1.5))
            
            # Случайное движение мыши
            if random.random() > 0.5:
                self.page.mouse.move(
                    random.randint(100, 800),
                    random.randint(100, 600)
                )
            
            # Случайная небольшая прокрутка
            if random.random() > 0.7:
                scroll_amount = random.randint(50, 200)
                self.page.evaluate(f"window.scrollBy(0, {scroll_amount});")
                time.sleep(random.uniform(0.3, 0.8))
        except Exception:
            pass
    
    def take_screenshot(self, filename: str, 
                       directory: Optional[str] = None,
                       full_page: bool = False) -> Dict[str, Any]:
        """
        Создание скриншота с улучшенной обработкой ошибок
        """
        if not self.session_active:
            return {"error": "Браузер не инициализирован"}
        
        if self.page is None:
            return {"error": "Страница не инициализирована"}
        
        logger.info(f"📸 Создание скриншота: {filename}")
        
        try:
            # Определение директории
            if directory is None:
                directory = str(config.SCREENSHOTS_DIR)
            
            full_dir = Path(directory).resolve()
            
            # Проверка на безопасность пути
            screenshots_base = Path(config.SCREENSHOTS_DIR).resolve()
            if not str(full_dir).startswith(str(screenshots_base)):
                return {"error": "Недопустимый путь к директории"}
            
            full_dir.mkdir(parents=True, exist_ok=True)
            
            # Очистка имени файла
            if not filename.strip():
                return {"error": "Имя файла не может быть пустым"}
            
            safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
            safe_filename = safe_filename.strip()
            
            if not safe_filename:
                return {"error": "Имя файла содержит только недопустимые символы"}
            
            # Определение формата
            if not any(safe_filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg"]):
                safe_filename += f".{config.SCREENSHOT_FORMAT.lower()}"
            
            file_path = (full_dir / safe_filename).resolve()
            
            # Проверка что файл находится в разрешенной директории
            if not str(file_path).startswith(str(full_dir)):
                return {"error": "Недопустимый путь к файлу"}
            
            # Определение формата для playwright
            fmt = 'png' if safe_filename.lower().endswith('.png') else 'jpeg'
            
            # Создать скриншот
            screenshot_options = {
                'path': str(file_path),
                'type': fmt,
                'full_page': full_page or getattr(config, 'SCREENSHOT_FULL_PAGE', False)
            }
            
            if fmt == 'jpeg':
                screenshot_options['quality'] = getattr(config, 'SCREENSHOT_QUALITY', 80)
            
            self.page.screenshot(**screenshot_options)
            
            # Проверка существования файла
            if not file_path.exists():
                return {"error": "Файл скриншота не был создан"}
            
            file_size = file_path.stat().st_size
            
            logger.info(f"✅ Скриншот сохранён: {file_path} ({file_size} bytes)")
            
            return {
                "status": "success",
                "file_path": str(file_path),
                "size": file_size,
                "filename": safe_filename
            }
            
        except PermissionError:
            error_msg = f"Нет прав на запись в директорию: {directory}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg}
        
        except OSError as e:
            error_msg = f"Ошибка файловой системы: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg}
        
        except Exception as e:
            error_msg = f"Неожиданная ошибка создания скриншота: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg}
    
    def search_web(self, query: str, search_engines: Optional[List[str]] = None,
                   max_results: int = 5) -> Dict[str, Any]:
        """Поиск в интернете с улучшенной обработкой"""
        if search_engines is None:
            search_engines = config.DEFAULT_SEARCH_ENGINES
        
        logger.info(f"🔍 Поиск в интернете: '{query}'")
        
        if not self.session_active and not self.initialize_browser():
            return {"error": "Не удалось инициализировать браузер"}
        
        assert self.page is not None
        
        results: List[Dict[str, Any]] = []
        q = urllib.parse.quote_plus(query)
        
        for engine in search_engines:
            base = config.SEARCH_ENGINES.get(engine)
            if not base:
                continue
            
            url = base.format(query=q)
            
            try:
                logger.info(f"🔎 Поиск через {engine}...")
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self.page.wait_for_selector('body', timeout=30000)
                
                # Проверка на капчу
                if self._detect_captcha():
                    logger.warning(f"🔒 Капча на {engine}, пропускаем...")
                    continue
                
                # Ждем результаты поиска
                ready_selectors: List[str] = config.WEB_SELECTORS.get(f"{engine}_results", [])
                ready_found: bool = False
                
                for rs in ready_selectors:
                    try:
                        self.page.wait_for_selector(rs, timeout=10000)
                        ready_found = True
                        break
                    except PlaywrightTimeoutError:
                        continue
                
                if not ready_found:
                    logger.warning(f"⚠️ Не удалось дождаться результатов для {engine}")
                    continue
                
                # Имитация поведения человека
                time.sleep(random.uniform(1, 2))
                
                # Извлечение результатов
                extracted = self._extract_search_results(engine=engine, max_results=max_results)
                for item in extracted:
                    item['engine'] = engine
                results.extend(extracted)
                
                if len(results) >= max_results:
                    break
                    
            except Exception as e:
                logger.warning(f"⚠️ Не удалось получить результаты из {engine}: {e}")
                continue
        
        return {
            "status": "success" if results else "partial",
            "query": query,
            "results": results[:max_results],
            "total_found": len(results)
        }
    
    def _extract_search_results(self, engine: str, max_results: int) -> List[Dict[str, Any]]:
        """Извлекает результаты поиска с текущей страницы"""
        assert self.page is not None
        
        sel_map = config.WEB_SELECTORS
        blocks_selectors: List[str] = sel_map.get(f"{engine}_results", [])
        extracted: List[Dict[str, Any]] = []
        
        for block_sel in blocks_selectors:
            try:
                blocks = self.page.locator(block_sel)
                count = blocks.count()
                
                for idx in range(min(count, max_results)):
                    try:
                        b = blocks.nth(idx)
                        
                        # Извлечение ссылки
                        link_locator = b.locator('a[href]')
                        if link_locator.count() == 0:
                            continue
                        
                        link = link_locator.first.get_attribute('href')
                        
                        # Извлечение заголовка
                        title = ''
                        for title_sel in ['h3', 'h2', 'a']:
                            try:
                                title_loc = b.locator(title_sel).first
                                if title_loc.count() > 0:
                                    title = title_loc.inner_text(timeout=1000)
                                    if title:
                                        break
                            except Exception:
                                continue
                        
                        # Извлечение сниппета
                        snippet = ''
                        for snippet_sel in ['div', 'span', 'p']:
                            try:
                                snippet_loc = b.locator(snippet_sel)
                                if snippet_loc.count() > 1:
                                    snippet = snippet_loc.nth(1).inner_text(timeout=1000)
                                    if snippet:
                                        break
                            except Exception:
                                continue
                        
                        if link:
                            extracted.append({
                                'title': title.strip(),
                                'link': link,
                                'snippet': snippet.strip()
                            })
                        
                        if len(extracted) >= max_results:
                            break
                    except Exception:
                        continue
            except Exception:
                continue
            
            if len(extracted) >= max_results:
                break
        
        return extracted
    
    def extract_text_from_page(self, selectors: Optional[List[str]] = None,
                               text_patterns: Optional[List[str]] = None) -> Dict[str, Any]:
        """Извлечение текста со страницы"""
        if not self.session_active:
            return {"error": "Браузер не инициализирован"}
        
        assert self.page is not None
        
        selectors = selectors or ["body"]
        collected: List[str] = []
        matches: Dict[str, List[str]] = {}
        
        try:
            for sel in selectors:
                try:
                    loc = self.page.locator(sel)
                    count = loc.count()
                    
                    for i in range(count):
                        try:
                            t = loc.nth(i).inner_text(timeout=5000)
                            if t:
                                collected.append(t.strip())
                        except Exception:
                            continue
                except Exception:
                    continue
            
            # Поиск по паттернам
            if text_patterns:
                for pat in text_patterns:
                    try:
                        rx = re.compile(pat, flags=re.IGNORECASE | re.MULTILINE)
                        found: List[str] = []
                        
                        for txt in collected:
                            found.extend(rx.findall(txt))
                        
                        if found:
                            matches[pat] = list({str(m) for m in found})
                    except Exception:
                        continue
            
            return {
                "status": "success",
                "selectors": selectors,
                "texts": collected,
                "matches": matches,
                "total_texts": len(collected)
            }
        except Exception as e:
            logger.error(f"❌ Ошибка извлечения текста: {str(e)}")
            return {"error": f"Ошибка извлечения текста: {str(e)}"}
    
    def find_contact_info(self, contact_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """Поиск контактной информации на странице"""
        if not self.session_active:
            return {"error": "Браузер не инициализирован"}
        
        assert self.page is not None
        
        contact_types = contact_types or ["phone", "email", "address"]
        found = {"phone": set(), "email": set(), "address": set()}
        
        try:
            # Получение селекторов секций
            sections_cfg = config.WEB_SELECTORS.get("contact_sections", {})
            section_selectors = list(sections_cfg.values()) if isinstance(sections_cfg, dict) else []
            section_selectors = section_selectors or ["body"]
            
            for sec_sel in section_selectors:
                try:
                    loc = self.page.locator(sec_sel)
                    count = loc.count()
                    
                    for i in range(count):
                        try:
                            text = loc.nth(i).inner_text(timeout=5000)
                            if not text:
                                continue
                            
                            # Поиск телефонов
                            if "phone" in contact_types:
                                phone_pattern = config.PATTERNS.get("phone", r"\+?\d[\d\s\-\(\)]{8,}")
                                for m in re.findall(phone_pattern, text):
                                    found["phone"].add(m if isinstance(m, str) else "".join(m))
                            
                            # Поиск email
                            if "email" in contact_types:
                                email_pattern = config.PATTERNS.get("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
                                for m in re.findall(email_pattern, text):
                                    found["email"].add(m if isinstance(m, str) else "".join(m))
                        except Exception:
                            continue
                except Exception:
                    continue
            
            return {
                "status": "success",
                "contacts": {k: sorted(list(v)) for k, v in found.items()},
                "total_found": sum(len(v) for v in found.values())
            }
        except Exception as e:
            logger.error(f"❌ Ошибка поиска контактов: {str(e)}")
            return {"error": f"Ошибка поиска контактов: {str(e)}"}
    
    def click_element(self, selector: str, by: str = "css", timeout: int = 10) -> Dict[str, Any]:
        """Клик по элементу"""
        if not self.session_active:
            return {"error": "Браузер не инициализирован"}
        
        assert self.page is not None
        
        logger.info(f"🖱️ Клик по элементу: {selector} (by={by})")
        
        try:
            loc = self.page.locator(selector if by != 'xpath' else f"xpath={selector}")
            loc.first.wait_for(state="visible", timeout=timeout * 1000)
            
            # Прокрутка к элементу
            loc.first.scroll_into_view_if_needed()
            time.sleep(0.3)
            
            # Клик
            loc.first.click()
            time.sleep(random.uniform(0.5, 1.0))
            
            logger.info("✅ Клик выполнен")
            return {"status": "success", "selector": selector}
            
        except PlaywrightTimeoutError:
            logger.error("❌ Таймаут ожидания элемента для клика")
            return {"error": "Таймаут ожидания элемента"}
        except Exception as e:
            logger.error(f"❌ Ошибка клика: {str(e)}")
            return {"error": f"Ошибка клика: {str(e)}"}
    
    def fill_form(self, form_fields: Dict[str, str], submit_selector: Optional[str] = None) -> Dict[str, Any]:
        """Заполнение формы"""
        if not self.session_active:
            return {"error": "Браузер не инициализирован"}
        
        assert self.page is not None
        
        filled_fields: List[str] = []
        errors: List[Dict[str, Any]] = []
        
        try:
            for key, value in form_fields.items():
                try:
                    # Поиск элемента несколькими способами
                    locator = None
                    
                    # 1) По метке
                    try:
                        locator = self.page.get_by_label(key, exact=False)
                        if locator.count() == 0:
                            locator = None
                    except Exception:
                        locator = None
                    
                    # 2) По имени
                    if locator is None:
                        locator = self.page.locator(f"input[name='{key}'], textarea[name='{key}'], select[name='{key}']")
                        if locator.count() == 0:
                            locator = None
                    
                    # 3) По id
                    if locator is None:
                        locator = self.page.locator(f"input#{key}, textarea#{key}, select#{key}")
                        if locator.count() == 0:
                            locator = None
                    
                    # 4) По placeholder
                    if locator is None:
                        locator = self.page.locator(f"input[placeholder*='{key}'], textarea[placeholder*='{key}']")
                        if locator.count() == 0:
                            locator = None
                    
                    if locator is None or locator.count() == 0:
                        errors.append({"field": key, "error": "Элемент не найден"})
                        continue
                    
                    el = locator.first
                    el.scroll_into_view_if_needed()
                    time.sleep(0.2)
                    
                    # Определение типа элемента
                    tag = el.evaluate("e => e.tagName.toLowerCase()")
                    
                    if tag in ("input", "textarea"):
                        el.fill(str(value))
                    elif tag == "select":
                        try:
                            el.select_option(label=str(value))
                        except Exception:
                            try:
                                el.select_option(value=str(value))
                            except Exception:
                                el.select_option(index=0)
                    else:
                        el.click()
                        self.page.keyboard.type(str(value), delay=random.randint(50, 150))
                    
                    filled_fields.append(key)
                    time.sleep(random.uniform(0.3, 0.7))
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка ввода для '{key}': {str(e)}")
                    errors.append({"field": key, "error": str(e)})
            
            # Отправка формы
            if submit_selector:
                try:
                    submit_el = self.page.locator(submit_selector).first
                    submit_el.wait_for(state="attached", timeout=5000)
                    submit_el.scroll_into_view_if_needed()
                    time.sleep(0.3)
                    submit_el.click()
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки формы: {str(e)}")
                    errors.append({"selector": submit_selector, "error": str(e)})
            else:
                # Поиск кнопки отправки
                try:
                    submit_buttons = [
                        "button[type='submit']",
                        "input[type='submit']",
                        "button:has-text('Submit')",
                        "button:has-text('Send')",
                        "button:has-text('Отправить')"
                    ]
                    
                    for btn_sel in submit_buttons:
                        try:
                            btn = self.page.locator(btn_sel).first
                            if btn.count() > 0:
                                btn.scroll_into_view_if_needed()
                                time.sleep(0.3)
                                btn.click()
                                time.sleep(1)
                                break
                        except Exception:
                            continue
                    else:
                        # Fallback: Enter
                        self.page.keyboard.press("Enter")
                        time.sleep(1)
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки формы (fallback): {str(e)}")
                    errors.append({"selector": "<fallback>", "error": str(e)})
            
            return {
                "status": "success" if not errors else "partial",
                "filled_fields": filled_fields,
                "errors": errors,
                "count": len(filled_fields)
            }
        except Exception as e:
            logger.error(f"❌ Ошибка заполнения формы: {str(e)}")
            return {"error": f"Ошибка заполнения формы: {str(e)}"}
    
    def scroll_page(self, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
        """Прокрутка страницы"""
        if not self.session_active:
            return {"error": "Браузер не инициализирован"}
        
        assert self.page is not None
        
        logger.info(f"📜 Прокрутка страницы: {direction} на {amount}px")
        
        try:
            if direction == "down":
                self.page.evaluate(f"window.scrollBy(0, {amount});")
            elif direction == "up":
                self.page.evaluate(f"window.scrollBy(0, -{amount});")
            elif direction == "bottom":
                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            elif direction == "top":
                self.page.evaluate("window.scrollTo(0, 0);")
            
            time.sleep(random.uniform(0.5, 1.0))
            
            logger.info(f"✅ Страница прокручена: {direction}")
            
            return {
                "status": "success",
                "direction": direction,
                "amount": amount
            }
        except Exception as e:
            logger.error(f"❌ Ошибка прокрутки: {str(e)}")
            return {"error": f"Ошибка прокрутки: {str(e)}"}
    
    def get_page_source(self, trim_length: Optional[int] = None) -> Dict[str, Any]:
        """Получение исходного кода страницы"""
        if not self.session_active:
            return {"error": "Браузер не инициализирован"}
        
        assert self.page is not None
        
        logger.info("📄 Получение исходного кода страницы")
        
        try:
            source: str = self.page.content()
            original_len: int = len(source)
            truncated: bool = False
            
            if isinstance(trim_length, int) and trim_length > 0 and original_len > trim_length:
                source = source[:trim_length]
                truncated = True
            
            logger.info(f"✅ Исходный код получен: {original_len} символов")
            
            return {
                "status": "success",
                "url": self.page.url,
                "source": source,
                "length": original_len,
                "truncated": truncated
            }
        except Exception as e:
            logger.error(f"❌ Ошибка получения исходного кода: {str(e)}")
            return {"error": f"Ошибка получения исходного кода: {str(e)}"}
    
    def execute_javascript(self, script: str) -> Dict[str, Any]:
        """Выполнение JavaScript"""
        if not self.session_active:
            return {"error": "Браузер не инициализирован"}
        
        assert self.page is not None
        
        logger.info(f"⚡ Выполнение JavaScript: {script[:100]}...")
        
        try:
            result = self.page.evaluate(script)
            
            logger.info(f"✅ JavaScript выполнен")
            
            return {
                "status": "success",
                "result": result
            }
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения JavaScript: {str(e)}")
            return {"error": f"Ошибка выполнения JavaScript: {str(e)}"}


# --- Глобальный менеджер браузера и модульные обёртки ---
browser_manager = BrowserManager()


def initialize_browser(
    headless: Optional[bool] = None, 
    use_existing: Optional[bool] = None, 
    cdp_url: Optional[str] = None, 
    debug_port: Optional[int] = None,
    enable_stealth: bool = True
) -> bool:
    """Модульная обёртка для инициализации браузера"""
    return browser_manager.initialize_browser(headless, use_existing, cdp_url, debug_port, enable_stealth)


def close_browser() -> Dict[str, Any]:
    """Модульная обёртка для закрытия браузера"""
    return browser_manager.close_browser()


def navigate_to_url(
    url: str, 
    wait_for_element: Optional[str] = None,
    timeout: int = 15,
    retry_on_captcha: bool = True,
    max_retries: int = 3
) -> Dict[str, Any]:
    """Модульная обёртка для перехода по URL"""
    return browser_manager.navigate_to_url(url, wait_for_element, timeout, retry_on_captcha, max_retries)


def take_screenshot(
    filename: str,
    directory: Optional[str] = None,
    full_page: bool = False
) -> Dict[str, Any]:
    """Модульная обёртка для создания скриншота"""
    return browser_manager.take_screenshot(filename, directory, full_page)


def search_web(
    query: str, 
    search_engines: Optional[List[str]] = None,
    max_results: int = 5
) -> Dict[str, Any]:
    """Модульная обёртка для поиска в интернете"""
    return browser_manager.search_web(query, search_engines, max_results)


def extract_text_from_page(
    selectors: Optional[List[str]] = None,
    text_patterns: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Модульная обёртка для извлечения текста со страницы"""
    return browser_manager.extract_text_from_page(selectors, text_patterns)


def find_contact_info(contact_types: Optional[List[str]] = None) -> Dict[str, Any]:
    """Модульная обёртка для поиска контактной информации"""
    return browser_manager.find_contact_info(contact_types)


def click_element(selector: str, by: str = "css", timeout: int = 10) -> Dict[str, Any]:
    """Модульная обёртка для клика по элементу"""
    return browser_manager.click_element(selector, by, timeout)


def fill_form(form_fields: Dict[str, str], submit_selector: Optional[str] = None) -> Dict[str, Any]:
    """Модульная обёртка для заполнения формы"""
    return browser_manager.fill_form(form_fields, submit_selector)


def scroll_page(direction: str = "down", amount: int = 500) -> Dict[str, Any]:
    """Модульная обёртка для прокрутки страницы"""
    return browser_manager.scroll_page(direction, amount)


def get_page_source(trim_length: Optional[int] = None) -> Dict[str, Any]:
    """Модульная обёртка для получения исходного кода страницы"""
    return browser_manager.get_page_source(trim_length)


def execute_javascript(script: str) -> Dict[str, Any]:
    """Модульная обёртка для выполнения JavaScript"""
    return browser_manager.execute_javascript(script)