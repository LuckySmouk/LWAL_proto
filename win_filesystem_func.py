# win-filesystem-func.py____________________________________________________________________________________________________

"""
УНИВЕРСАЛЬНЫЙ модуль для работы с файловой системой Windows.
Поддерживает все типы файлов и автоматически определяет форматы.

ФУНКЦИИ:
=========
- read_file(): прочитать файл любого типа (txt, json, csv, xlsx, pdf, изображения и т.д.)
- write_file(): записать файл с автоматическим определением формата
- read_file_chunked(): чтение больших файлов по частям
- delete_file(): удалить файл
- list_directory(): получить список файлов в папке
- copy_file(): скопировать файл
- move_file(): переместить или переименовать файл
- create_directory(): создать папку (с вложенными уровнями)
- get_file_info(): получить информацию о файле (размер, дату, атрибуты)
- search_in_files(): поиск текста в файлах
- write_csv_file(): запись данных в CSV таблицу

АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ ТИПОВ:
==================================
JSON → загружается как структурированный объект
CSV → загружается как таблица (список словарей)
Excel (.xlsx, .xls) → загружается как таблица
Изображения (.jpg, .png, .gif) → возвращается информация о файле
PDF → возвращается информация, готовность к анализу
Текстовые файлы (txt, py, js, html и т.д.) → загружается как текст
Архивы (zip, rar, 7z) → возвращается информация об архиве

КОДИРОВАНИЕ:
============
Автоматическое определение кодировки файлов (UTF-8, CP1251, ASCII и т.д.)
Все операции безопасны для русского текста.

НОРМАЛИЗАЦИЯ РЕЗУЛЬТАТОВ:
========================
Все функции возвращают Dict с полями:
{
    "status": "success|error|partial",
    "error": null или сообщение об ошибке,
    "stdout": вывод если применимо,
    "stderr": ошибки вывода,
    "file_path": путь к файлу,
    ... специфичные для функции поля (content, size, encoding, type и т.д.)
}
"""
import os
import shutil
import json
import csv
import pandas as pd
import chardet
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
import config

logger = config.logger

def normalize_fs_result(result: Any) -> Dict[str, Any]:
    """Нормализует результаты файловых операций в единую форму"""
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
            # Для файловых операций нормализуем file_path
            if "file_path" not in res:
                for k in ("filepath", "path"):
                    if k in res and isinstance(res.get(k), str):
                        res["file_path"] = res.get(k)
                        break
            res["stdout"] = "" if res.get("stdout") is None else str(res.get("stdout"))
            res["stderr"] = "" if res.get("stderr") is None else str(res.get("stderr"))
            return res
        
        return {"status": "success", "error": None, "stdout": str(result), "stderr": ""}
    except Exception:
        return {"status": "error", "error": "normalization_failed", "stdout": "", "stderr": ""}

class FileSystemManager:
    """Универсальное управление файловой системой с поддержкой всех форматов"""
    
    def __init__(self):
        self.base_dir: Path = Path(config.DOCUMENTS_DIR)
        
    def _detect_encoding(self, filepath: str) -> str:
        """Автоматически определяет кодировку файла (оптимизировано для Windows)"""
        try:
            with open(filepath, 'rb') as f:
                # Читаем достаточно данных для точного определения
                file_size = Path(filepath).stat().st_size
                read_size = min(max(50000, file_size), 200000)  # От 50KB до 200KB
                raw_data = f.read(read_size)
                
                # Проверяем BOM (Byte Order Mark)
                if raw_data.startswith(b'\xef\xbb\xbf'):
                    return 'utf-8-sig'
                elif raw_data.startswith(b'\xff\xfe'):
                    return 'utf-16-le'
                elif raw_data.startswith(b'\xfe\xff'):
                    return 'utf-16-be'
                
                #   Пробуем определить через chardet
                result = chardet.detect(raw_data) or {}
                encoding_raw = result.get('encoding')
                encoding = str(encoding_raw).lower() if encoding_raw else ''
                confidence = result.get('confidence', 0) or 0
                
                logger.debug(f"🔍 Определение кодировки: {encoding} (уверенность: {confidence:.2f})")
                
                # Приоритетная обработка для Windows
                # Если найдена ASCII с низкой уверенностью - пробуем cp1251
                if encoding in ('ascii', '') and confidence < 0.8:
                    # Проверяем наличие кириллицы (байты 0xC0-0xFF)
                    cyrillic_bytes = sum(1 for b in raw_data if 0xC0 <= b <= 0xFF)
                    if cyrillic_bytes > len(raw_data) * 0.05:  # Более 5% кириллицы
                        logger.info("🔤 Обнаружена кириллица, используем cp1251")
                        return 'cp1251'
                    return 'utf-8'
                
                # Нормализация кодировок для Windows
                encoding_map = {
                    'ascii': 'utf-8',
                    'windows-1251': 'cp1251',
                    'cp1251': 'cp1251',
                    'iso-8859-1': 'cp1251',  # Часто неверно определяется
                    'maccyrillic': 'cp1251',
                    'koi8-r': 'cp1251',  # На Windows редко используется
                    'utf-8': 'utf-8',
                    'utf-16': 'utf-16'
                }
                
                normalized = encoding_map.get(encoding, encoding)
                
                # Если уверенность низкая - пробуем cp1251 как fallback для Windows
                if confidence < 0.7 and normalized not in ('utf-8', 'cp1251'):
                    logger.warning(f"⚠️ Низкая уверенность ({confidence:.2f}), используем cp1251 как fallback")
                    return 'cp1251'
                
                return normalized if normalized else 'utf-8'
                
        except Exception as e:
            logger.warning(f"⚠️ Ошибка определения кодировки: {e}, используем utf-8")
            return 'utf-8'
    
    def read_file(self, filepath: str, encoding: str = 'auto') -> Dict[str, Any]:
        """Читает содержимое файла любого формата"""
        logger.info(f"📖 Чтение файла: {filepath}")
        logger.debug(f"   Кодировка: {encoding}")
        
        try:
            path = Path(filepath)
            
            if not path.exists():
                return {"error": f"Файл не найден: {filepath}", "status": "error"}
            
            if not path.is_file():
                return {"error": f"Путь не является файлом: {filepath}", "status": "error"}
            
            # Проверка размера файла
            file_size_mb = path.stat().st_size / (1024 * 1024)
            if file_size_mb > config.SECURITY_CONFIG['max_file_size_mb']:
                return {"error": f"Файл слишком большой: {file_size_mb:.2f} MB", "status": "error"}
            
            # Проверка на пустой файл
            if path.stat().st_size == 0:
                logger.info("📄 Файл пустой")
                return {
                    "status": "success",
                    "filepath": str(path),
                    "filename": path.name,
                    "content": "",
                    "type": "text",
                    "size": 0,
                    "encoding": "utf-8",
                    "note": "Файл пустой (0 байт)"
                }
            
            # Автоопределение кодировки
            detected_encoding = self._detect_encoding(str(path)) if encoding == 'auto' else encoding
            
            file_info = {
                "status": "success",
                "filepath": str(path),
                "filename": path.name,
                "extension": path.suffix.lower(),
                "size": path.stat().st_size,
                "size_mb": round(file_size_mb, 2),
                "encoding": detected_encoding,
                "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "created": datetime.fromtimestamp(path.stat().st_ctime).isoformat()
            }
            
            # Чтение в зависимости от типа файла
            file_extension = path.suffix.lower()
            
            try:
                if file_extension == '.json':
                    with open(path, 'r', encoding=detected_encoding) as f:
                        file_info["content"] = json.load(f)
                        file_info["type"] = "json"
                        file_info["structure"] = "parsed_json"
                        
                elif file_extension == '.csv':
                    # Пытаемся прочитать как CSV с разными разделителями
                    try:
                        df = pd.read_csv(path, encoding=detected_encoding)
                        file_info["content"] = df.to_dict('records')
                        file_info["type"] = "csv"
                        file_info["structure"] = "tabular_data"
                        file_info["columns"] = df.columns.tolist()
                        file_info["rows_count"] = len(df)
                    except Exception as csv_error:
                        # Fallback: читаем как текст
                        with open(path, 'r', encoding=detected_encoding) as f:
                            file_info["content"] = f.read()
                            file_info["type"] = "text"
                            file_info["structure"] = "raw_text"
                
                elif file_extension in ['.txt', '.log', '.md', '.py', '.js', '.html', '.css', '.xml']:
                    # Пытаемся прочитать с определенной кодировкой
                    content = None
                    encodings_to_try = [detected_encoding, 'utf-8', 'cp1251', 'latin-1']
                    
                    for enc in encodings_to_try:
                        try:
                            with open(path, 'r', encoding=enc) as f:
                                content = f.read()
                                if enc != detected_encoding:
                                    logger.info(f"✅ Файл прочитан с кодировкой {enc} (fallback)")
                                    file_info["encoding"] = enc
                                break
                        except (UnicodeDecodeError, LookupError):
                            if enc == encodings_to_try[-1]:
                                # Последняя попытка - читаем как binary и декодируем с игнорированием ошибок
                                logger.warning(f"⚠️ Не удалось определить кодировку, читаем с errors='replace'")
                                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                                    content = f.read()
                                    file_info["encoding"] = "utf-8 (with errors replaced)"
                                    file_info["warning"] = "Некоторые символы могут быть заменены из-за проблем с кодировкой"
                            continue
                    
                    if content is not None:
                        file_info["content"] = content
                        file_info["type"] = "text"
                        file_info["structure"] = "raw_text"
                        file_info["lines_count"] = len(content.splitlines())
                    else:
                        raise ValueError("Не удалось прочитать файл ни с одной кодировкой")
                
                elif file_extension in ['.xlsx', '.xls']:
                    try:
                        df = pd.read_excel(path)
                        file_info["content"] = df.to_dict('records')
                        file_info["type"] = "excel"
                        file_info["structure"] = "tabular_data"
                        file_info["columns"] = df.columns.tolist()
                        file_info["rows_count"] = len(df)
                        file_info["sheets"] = pd.ExcelFile(path).sheet_names
                    except Exception as excel_error:
                        file_info["content"] = f"Excel файл (не удалось прочитать: {str(excel_error)})"
                        file_info["type"] = "binary"
                
                elif file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                    file_info["content"] = f"Изображение: {path.name} ({file_info['size_mb']} MB)"
                    file_info["type"] = "image"
                    file_info["structure"] = "binary_image"
                    file_info["analysis_ready"] = True  # Готов для analyze_image
                
                elif file_extension in ['.pdf']:
                    file_info["content"] = f"PDF документ: {path.name} ({file_info['size_mb']} MB)"
                    file_info["type"] = "pdf"
                    file_info["structure"] = "binary_document"
                    file_info["note"] = "Для извлечения текста используйте analyze_image с вопросом 'извлеки текст из этого PDF'"
                
                elif file_extension in ['.zip', '.rar', '.7z']:
                    file_info["content"] = f"Архив: {path.name} ({file_info['size_mb']} MB)"
                    file_info["type"] = "archive"
                    file_info["structure"] = "binary_archive"
                
                else:
                    # Для неизвестных форматов пробуем прочитать как текст
                    try:
                        with open(path, 'r', encoding=detected_encoding) as f:
                            content = f.read()
                            file_info["content"] = content
                            file_info["type"] = "text"
                            file_info["structure"] = "raw_text"
                    except UnicodeDecodeError:
                        # Если не текстовый файл - возвращаем информацию о бинарном файле
                        file_info["content"] = f"Бинарный файл: {path.name} ({file_info['size_mb']} MB)"
                        file_info["type"] = "binary"
                        file_info["structure"] = "binary_data"
                
                logger.info(f"✅ Файл прочитан: {filepath} (тип: {file_info.get('type', 'unknown')})")
                return file_info
                
            except PermissionError:
                error_msg = f"Нет доступа к файлу: {filepath}"
                logger.error(f"❌ {error_msg}")
                return {"error": error_msg, "status": "error"}
            except Exception as e:
                error_msg = f"Ошибка чтения файла {filepath}: {str(e)}"
                logger.error(f"❌ {error_msg}")
                return {"error": error_msg, "status": "error"}
            
        except Exception as e:
            error_msg = f"Критическая ошибка при обработке файла {filepath}: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg, "status": "error"}
    
    def write_file(self, filepath: str, content: Any, 
                   encoding: str = 'utf-8', overwrite: bool = True) -> Dict[str, Any]:
        """Записывает содержимое в файл с поддержкой различных форматов"""
        logger.info(f"💾 Запись в файл: {filepath}")
        
        try:
            path = Path(filepath)
            
            # Создание директории если не существует
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Проверка на перезапись
            if path.exists() and not overwrite:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                name = path.stem
                ext = path.suffix
                path = path.parent / f"{name}_{timestamp}{ext}"
                logger.info(f"📝 Файл уже существует, создан новый: {path}")
            
            file_extension = path.suffix.lower()
            
            # Запись в зависимости от типа контента и расширения файла
            if file_extension == '.json' or isinstance(content, (dict, list)):
                with open(path, 'w', encoding=encoding) as f:
                    json.dump(content, f, ensure_ascii=False, indent=2)
            
            elif file_extension == '.csv' and isinstance(content, list):
                # Запись CSV из списка словарей
                if content and isinstance(content[0], dict):
                    headers = list(content[0].keys())
                    with open(path, 'w', newline='', encoding=encoding) as f:
                        writer = csv.DictWriter(f, fieldnames=headers)
                        writer.writeheader()
                        writer.writerows(content)
                else:
                    with open(path, 'w', encoding=encoding) as f:
                        f.write(str(content))
            
            else:
                # Запись как обычный текст
                with open(path, 'w', encoding=encoding) as f:
                    f.write(str(content))
            
            logger.info(f"✅ Файл записан: {path}")
            
            return {
                "status": "success",
                "filepath": str(path),
                "size": path.stat().st_size,
                "size_mb": round(path.stat().st_size / (1024 * 1024), 2)
            }
            
        except PermissionError:
            logger.error(f"❌ Нет прав для записи: {filepath}")
            return {"error": f"Нет прав для записи: {filepath}", "status": "error"}
        except Exception as e:
            logger.error(f"❌ Ошибка записи файла: {str(e)}")
            return {"error": f"Ошибка записи файла: {str(e)}", "status": "error"}
    
    def read_file_chunked(self, filepath: str, chunk_size: int = 8192, 
                         encoding: str = 'auto') -> Dict[str, Any]:
        """Читает большой файл по частям"""
        logger.info(f"📖 Чтение файла по частям: {filepath}")
        
        try:
            path = Path(filepath)
            
            if not path.exists():
                return {"error": f"Файл не найден: {filepath}", "status": "error"}
            
            detected_encoding = self._detect_encoding(str(path)) if encoding == 'auto' else encoding
            
            file_info = {
                "status": "success",
                "filepath": str(path),
                "filename": path.name,
                "size": path.stat().st_size,
                "chunk_size": chunk_size,
                "encoding": detected_encoding,
                "chunks": []
            }
            
            # Чтение файла по частям
            with open(path, 'r', encoding=detected_encoding) as f:
                chunk_number = 0
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    
                    file_info["chunks"].append({
                        "chunk_number": chunk_number,
                        "content": chunk,
                        "size": len(chunk)
                    })
                    chunk_number += 1
            
            file_info["total_chunks"] = chunk_number
            logger.info(f"✅ Файл прочитан по частям: {filepath} ({chunk_number} чанков)")
            
            return file_info
            
        except Exception as e:
            error_msg = f"Ошибка чтения файла по частям: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg, "status": "error"}
    
    def search_in_files(self, directory: str, search_text: str, 
                       file_pattern: str = "*", recursive: bool = True) -> Dict[str, Any]:
        """Поиск текста в файлах"""
        logger.info(f"🔍 Поиск '{search_text}' в {directory}")
        
        try:
            path = Path(directory)
            
            if not path.exists():
                return {"error": f"Директория не найдена: {directory}", "status": "error"}
            
            results = []
            search_pattern = path.rglob(file_pattern) if recursive else path.glob(file_pattern)
            
            for file_path in search_pattern:
                if file_path.is_file():
                    try:
                        # Пропускаем бинарные файлы большого размера
                        if file_path.stat().st_size > 10 * 1024 * 1024:  # 10MB
                            continue
                            
                        file_encoding = self._detect_encoding(str(file_path))
                        with open(file_path, 'r', encoding=file_encoding) as f:
                            content = f.read()
                            if search_text.lower() in content.lower():
                                # Находим контекст вокруг найденного текста
                                lines = content.splitlines()
                                matches = []
                                for i, line in enumerate(lines):
                                    if search_text.lower() in line.lower():
                                        start = max(0, i-2)
                                        end = min(len(lines), i+3)
                                        context = '\n'.join(lines[start:end])
                                        matches.append({
                                            "line_number": i+1,
                                            "line": line,
                                            "context": context
                                        })
                                
                                results.append({
                                    "file": str(file_path),
                                    "matches": matches,
                                    "match_count": len(matches)
                                })
                                
                    except Exception as e:
                        # Пропускаем файлы которые не удалось прочитать
                        continue
            
            logger.info(f"✅ Поиск завершен. Найдено совпадений: {len(results)}")
            
            return {
                "status": "success",
                "search_text": search_text,
                "directory": directory,
                "results": results,
                "total_matches": len(results)
            }
            
        except Exception as e:
            error_msg = f"Ошибка поиска в файлах: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg, "status": "error"}
    
    def get_file_statistics(self, filepath: str) -> Dict[str, Any]:
        """Получает статистику файла"""
        logger.info(f"📊 Статистика файла: {filepath}")
        
        try:
            path = Path(filepath)
            
            if not path.exists():
                return {"error": f"Файл не найден: {filepath}", "status": "error"}
            
            # Читаем файл для анализа
            file_data = self.read_file(filepath)
            if file_data.get("status") != "success":
                return file_data
            
            content = file_data.get("content", "")
            file_type = file_data.get("type", "unknown")
            
            stats = {
                "status": "success",
                "filepath": str(path),
                "filename": path.name,
                "type": file_type,
                "size_bytes": path.stat().st_size,
                "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
                "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            }
            
            # Статистика в зависимости от типа файла
            if file_type == "text" and isinstance(content, str):
                lines = content.splitlines()
                stats.update({
                    "lines_count": len(lines),
                    "words_count": len(content.split()),
                    "characters_count": len(content),
                    "non_empty_lines": len([line for line in lines if line.strip()])
                })
            elif (file_type == "csv" or file_type == "excel") and isinstance(content, list):
                stats.update({
                    "rows_count": len(content),
                    "columns_count": len(content[0]) if content else 0,
                    "columns": list(content[0].keys()) if content else []
                })
            
            logger.info(f"✅ Статистика собрана: {filepath}")
            return stats
            
        except Exception as e:
            error_msg = f"Ошибка сбора статистики: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg, "status": "error"}
    
    # Сохраняем существующие методы с улучшенной обработкой ошибок
    def delete_file(self, filepath: str, confirm: bool = False) -> Dict[str, Any]:
        """Удаляет файл"""
        logger.info(f"🗑️ Удаление файла: {filepath}")
        
        if not confirm and config.SECURITY_CONFIG['safe_mode']:
            return {
                "status": "confirmation_required",
                "message": f"Требуется подтверждение для удаления: {filepath}",
                "filepath": filepath
            }
        
        try:
            path = Path(filepath)
            
            if not path.exists():
                return {"error": f"Файл не найден: {filepath}", "status": "error"}
            
            if path.is_file():
                # Создаем резервную копию перед удалением
                backup_path = path.parent / f"{path.stem}_backup_{datetime.now().strftime('%H%M%S')}{path.suffix}"
                shutil.copy2(path, backup_path)
                
                path.unlink()
                logger.info(f"✅ Файл удалён: {filepath} (резервная копия: {backup_path})")
                return {
                    "status": "success",
                    "message": f"Файл удалён: {filepath}",
                    "backup_created": str(backup_path)
                }
            else:
                return {"error": f"Путь не является файлом: {filepath}", "status": "error"}
                
        except PermissionError:
            logger.error(f"❌ Нет прав для удаления: {filepath}")
            return {"error": f"Нет прав для удаления: {filepath}", "status": "error"}
        except Exception as e:
            logger.error(f"❌ Ошибка удаления файла: {str(e)}")
            return {"error": f"Ошибка удаления файла: {str(e)}", "status": "error"}
    
    def list_directory(self, dirpath: str, pattern: str = "*", 
                       recursive: bool = False) -> Dict[str, Any]:
        """Список файлов в директории"""
        logger.info(f"📂 Список файлов в: {dirpath}")
        
        try:
            path = Path(dirpath)
            
            if not path.exists():
                return {"error": f"Директория не найдена: {dirpath}", "status": "error"}
            
            if not path.is_dir():
                return {"error": f"Путь не является директорией: {dirpath}", "status": "error"}
            
            # Получение списка файлов
            if recursive:
                files = list(path.rglob(pattern))
            else:
                files = list(path.glob(pattern))
            
            # Формирование детальной информации
            file_list = []
            total_size = 0
            
            for file in files:
                try:
                    stat = file.stat()
                    file_size = stat.st_size if file.is_file() else 0
                    total_size += file_size
                    
                    file_list.append({
                        "name": file.name,
                        "path": str(file),
                        "type": "file" if file.is_file() else "directory",
                        "size": file_size,
                        "size_mb": round(file_size / (1024 * 1024), 2),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "extension": file.suffix if file.is_file() else "",
                        "permissions": oct(stat.st_mode)[-3:]
                    })
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка получения информации о {file}: {e}")
                    continue
            
            logger.info(f"✅ Найдено файлов: {len(file_list)}")
            
            return {
                "status": "success",
                "directory": str(path),
                "pattern": pattern,
                "recursive": recursive,
                "count": len(file_list),
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "files": file_list
            }
            
        except PermissionError:
            logger.error(f"❌ Нет доступа к директории: {dirpath}")
            return {"error": f"Нет доступа к директории: {dirpath}", "status": "error"}
        except Exception as e:
            logger.error(f"❌ Ошибка чтения директории: {str(e)}")
            return {"error": f"Ошибка чтения директории: {str(e)}", "status": "error"}
    
    def copy_file(self, source: str, destination: str, 
                  overwrite: bool = False) -> Dict[str, Any]:
        """Копирует файл"""
        logger.info(f"📋 Копирование: {source} -> {destination}")
        
        try:
            src_path = Path(source)
            dest_path = Path(destination)
            
            if not src_path.exists():
                return {"error": f"Исходный файл не найден: {source}", "status": "error"}
            
            if dest_path.exists() and not overwrite:
                return {"error": f"Файл назначения уже существует: {destination}", "status": "error"}
            
            # Создание директории назначения
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Копирование с сохранением метаданных
            shutil.copy2(src_path, dest_path)
            
            logger.info(f"✅ Файл скопирован: {destination}")
            
            return {
                "status": "success",
                "source": str(src_path),
                "destination": str(dest_path),
                "size": dest_path.stat().st_size,
                "size_mb": round(dest_path.stat().st_size / (1024 * 1024), 2)
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка копирования файла: {str(e)}")
            return {"error": f"Ошибка копирования файла: {str(e)}", "status": "error"}
    
    def move_file(self, source: str, destination: str, 
                  overwrite: bool = False) -> Dict[str, Any]:
        """Перемещает файл"""
        logger.info(f"➡️ Перемещение: {source} -> {destination}")
        
        try:
            src_path = Path(source)
            dest_path = Path(destination)
            
            if not src_path.exists():
                return {"error": f"Исходный файл не найден: {source}", "status": "error"}
            
            if dest_path.exists() and not overwrite:
                return {"error": f"Файл назначения уже существует: {destination}", "status": "error"}
            
            # Создание директории назначения
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Перемещение
            shutil.move(str(src_path), str(dest_path))
            
            logger.info(f"✅ Файл перемещён: {destination}")
            
            return {
                "status": "success",
                "source": str(src_path),
                "destination": str(dest_path)
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка перемещения файла: {str(e)}")
            return {"error": f"Ошибка перемещения файла: {str(e)}", "status": "error"}
    
    def create_directory(self, dirpath: str) -> Dict[str, Any]:
        """Создаёт директорию"""
        logger.info(f"📁 Создание директории: {dirpath}")
        
        try:
            path = Path(dirpath)
            path.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"✅ Директория создана: {dirpath}")
            
            return {
                "status": "success",
                "directory": str(path),
                "created": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания директории: {str(e)}")
            return {"error": f"Ошибка создания директории: {str(e)}", "status": "error"}
    
    def get_file_info(self, filepath: str) -> Dict[str, Any]:
        """Получает информацию о файле"""
        logger.info(f"ℹ️ Информация о файле: {filepath}")
        
        try:
            path = Path(filepath)
            
            if not path.exists():
                return {"error": f"Файл не найден: {filepath}", "status": "error"}
            
            stat = path.stat()
            
            info = {
                "status": "success",
                "path": str(path),
                "name": path.name,
                "type": "file" if path.is_file() else "directory",
                "size": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "extension": path.suffix if path.is_file() else "",
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "accessed": datetime.fromtimestamp(stat.st_atime).isoformat(),
                "parent": str(path.parent),
                "permissions": oct(stat.st_mode)[-3:],
                "inode": stat.st_ino
            }
            
            logger.info(f"✅ Информация получена: {path.name}")
            
            return info
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о файле: {str(e)}")
            return {"error": f"Ошибка получения информации о файле: {str(e)}", "status": "error"}

    def write_csv_file(self, filepath: str, data: List[Dict[str, Any]], headers: Optional[List[str]] = None, overwrite: bool = False) -> Dict[str, Any]:
        """Записывает данные в CSV файл"""
        logger.info(f"📊 Запись CSV файла: {filepath}")
        try:
            path = Path(filepath)
            if path.exists() and not overwrite:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                name = path.stem
                ext = path.suffix
                path = path.parent / f"{name}_{timestamp}{ext}"
                logger.info(f"📝 Файл уже существует, создан новый: {path}")
            
            # Создание директории если не существует
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Определяем заголовки
            if headers is None and data:
                headers = list(data[0].keys())
            elif headers is None:
                headers = []
            
            # Запись CSV
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
                writer.writeheader()
                for row in data:
                    # Преобразуем все значения в строки
                    row_str = {k: str(v) if v is not None else '' for k, v in row.items()}
                    writer.writerow(row_str)
            
            logger.info(f"✅ CSV файл записан: {path} ({len(data)} строк)")
            
            return {
                "status": "success",
                "file_path": str(path),
                "rows": len(data),
                "columns": len(headers),
                "size": path.stat().st_size
            }
        except Exception as e:
            logger.error(f"❌ Ошибка записи CSV файла: {str(e)}")
            return {"error": f"Ошибка записи CSV файла: {str(e)}", "status": "error"}

    def write_excel_file(self, filepath: str, data: List[Dict[str, Any]], sheet_name: str = 'Sheet1', overwrite: bool = True) -> Dict[str, Any]:
        """Записывает данные в Excel файл (.xlsx)"""
        logger.info(f"📊 Запись Excel файла: {filepath}")
        try:
            path = Path(filepath)
            if path.exists() and not overwrite:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = path.parent / f"{path.stem}_{timestamp}{path.suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            import pandas as _pd
            df = _pd.DataFrame(data or [])
            with _pd.ExcelWriter(path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
            return {"status": "success", "file_path": str(path), "rows": len(df)}
        except Exception as e:
            logger.error(f"❌ Ошибка записи Excel файла: {e}")
            return {"error": f"Ошибка записи Excel файла: {e}", "status": "error"}


# Создаём глобальный экземпляр
fs_manager = FileSystemManager()


# Экспортируемые функции
def read_file(filepath: str, encoding: str = 'auto') -> Dict[str, Any]:
    """Читает файл любого формата"""
    return fs_manager.read_file(filepath, encoding)


def read_file_chunked(filepath: str, chunk_size: int = 8192, 
                     encoding: str = 'auto') -> Dict[str, Any]:
    """Читает большой файл по частям"""
    return fs_manager.read_file_chunked(filepath, chunk_size, encoding)


def search_in_files(directory: str, search_text: str, 
                   file_pattern: str = "*", recursive: bool = True) -> Dict[str, Any]:
    """Поиск текста в файлах"""
    return fs_manager.search_in_files(directory, search_text, file_pattern, recursive)


def get_file_statistics(filepath: str) -> Dict[str, Any]:
    """Получает статистику файла"""
    return fs_manager.get_file_statistics(filepath)


def write_file(filepath: str, content: Any, encoding: str = 'utf-8', 
               overwrite: bool = True) -> Dict[str, Any]:
    """Записывает файл"""
    return fs_manager.write_file(filepath, content, encoding, overwrite)


def write_csv_file(filepath: str, data: List[Dict[str, Any]], 
                   headers: Optional[List[str]] = None, 
                   overwrite: bool = True) -> Dict[str, Any]:
    """Записывает данные в CSV файл"""
    logger.info(f"📊 Запись CSV файла: {filepath}")
    
    try:
        path = Path(filepath)
        
        # Создание директории если не существует
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Проверка на перезапись
        if path.exists() and not overwrite:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = path.stem
            ext = path.suffix
            path = path.parent / f"{name}_{timestamp}{ext}"
            logger.info(f"📝 Файл уже существует, создан новый: {path}")
        
        # Определяем заголовки
        if headers is None and data:
            headers = list(data[0].keys())
        elif headers is None:
            headers = []
        
        # Запись CSV
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
            writer.writeheader()
            for row in data:
                # Преобразуем все значения в строки
                row_str = {k: str(v) if v is not None else '' for k, v in row.items()}
                writer.writerow(row_str)
        
        logger.info(f"✅ CSV файл записан: {path} ({len(data)} строк)")
        
        return {
            "status": "success",
            "file_path": str(path),
            "rows": len(data),
            "columns": len(headers),
            "size": path.stat().st_size
        }
    except Exception as e:
        logger.error(f"❌ Ошибка записи CSV файла: {str(e)}")
        return {"error": f"Ошибка записи CSV файла: {str(e)}", "status": "error"}


def delete_file(filepath: str, confirm: bool = False) -> Dict[str, Any]:
    """Удаляет файл"""
    return fs_manager.delete_file(filepath, confirm)


def list_directory(dirpath: str, pattern: str = "*", 
                   recursive: bool = False) -> Dict[str, Any]:
    """Список файлов в директории"""
    return fs_manager.list_directory(dirpath, pattern, recursive)


def copy_file(source: str, destination: str, 
              overwrite: bool = False) -> Dict[str, Any]:
    """Копирует файл"""
    return fs_manager.copy_file(source, destination, overwrite)


def move_file(source: str, destination: str, 
              overwrite: bool = False) -> Dict[str, Any]:
    """Перемещает файл"""
    return fs_manager.move_file(source, destination, overwrite)


def create_directory(dirpath: str) -> Dict[str, Any]:
    """Создаёт директорию"""
    return fs_manager.create_directory(dirpath)


def get_file_info(filepath: str) -> Dict[str, Any]:
    """Получает информацию о файле"""
    return fs_manager.get_file_info(filepath)

def write_excel_file(filepath: str, data: List[Dict[str, Any]], sheet_name: str = 'Sheet1', overwrite: bool = True) -> Dict[str, Any]:
    return fs_manager.write_excel_file(filepath, data, sheet_name, overwrite)


__all__ = [
    'read_file',
    'write_file',
    'read_file_chunked',
    'delete_file',
    'list_directory',
    'copy_file',
    'move_file',
    'create_directory',
    'get_file_info',
    'search_in_files',
    'get_file_statistics',
    'write_csv_file',
    'write_excel_file',  # Добавьте эту строку
    'FileSystemManager',
    'fs_manager'
]