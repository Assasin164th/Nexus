import sys
import os
import shutil
import time
import requests
import json
import re
import glob
from datetime import datetime, timedelta
import pytesseract
from PIL import Image
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QFrame, QListWidget,
    QListWidgetItem, QDialog, QDialogButtonBox, QSpinBox, QDateEdit,
    QMessageBox, QStatusBar, QProgressBar, QTextEdit, QLayout
)
from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal, QObject, QSettings
from PyQt6.QtGui import QFont, QTextCursor

# Свои импорты
from postsList import PostsListWindow
from document_creator import DocumentCreator
from test import create_document_from_json

# Импорты для GigaChat
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

# ------------------ Настройка Tesseract ------------------
TESSERACT_PATH = r'C:\Users\неликаеванс\Desktop\Test\Nina Parsing\Tesseract\tesseract.exe'
TESSDATA_PATH = r'C:\Users\неликаеванс\Desktop\Test\Nina Parsing\Tesseract\tessdata'

# Устанавливаем путь к tesseract.exe
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# Устанавливаем переменную окружения для папки tessdata
os.environ['TESSDATA_PREFIX'] = TESSDATA_PATH

# Проверяем, существует ли файл языка
if not os.path.exists(os.path.join(TESSDATA_PATH, 'rus.traineddata')):
    print(f"ВНИМАНИЕ: Файл rus.traineddata не найден в {TESSDATA_PATH}")

# ------------------ Конфигурация VK ------------------
VERSION = 5.199

# ------------------ Список групп ------------------
GROUPS = [
    'ОПИ-25', 'ГЭМ-25-1', 'ГЭМ-25-2', 'МП-25', 'ТМ-25', 'ТО-25', 'ОПЖТ-25', 'СЭЗ-25',
    'И-25', 'СА-25', 'ИСП-25', 'ИСП(в)-25', 'ОДЛ-25', 'ПД-25-1', 'ПД-25-2', 'ПД-25-3',
    'КР-25', 'ЭМ-25', 'ОДР-25', 'ОПИ-24', 'ГЭМ-24-1', 'ГЭМ-24-2', 'МП-24', 'ТМ-24',
    'ТОР-24', 'ОПЖТ-24', 'СЭЗ-24', 'И-24', 'СА-24', 'ИСП-24', 'ОДЛ-24', 'ПД-24-1',
    'ПД-24-2', 'ПД-24-3', 'КР-24', 'ЭМ-24', 'ОДР-24', 'ОПИ-23', 'ГЭ-23-1', 'ГЭ-23-2',
    'МЧМ-23', 'ТОР-23', 'ОПЖТ-23', 'СЭЗ-23', 'И-23', 'СА-23', 'ИСП-23', 'ОДЛ-23',
    'ПД-23-1', 'ПД-23-2', 'ТМ-23', 'ТОР-22', 'И-22', 'ИСП-22', 'ТМП-22', 'ПД-22', 'СА-22'
]

# ------------------ Вспомогательные функции ------------------
def normalize_text(text):
    return re.sub(r'[‒–—―‑]', '-', text)

def log_gigachat_response(text, context=""):
    """Сохраняет ответ нейросети в файл с меткой времени и контекстом."""
    try:
        with open("gigachat_responses.log", "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {context}\n{text}\n{'-'*50}\n")
    except Exception:
        pass

def find_groups(text, group_list=None):
    if group_list is None:
        group_list = GROUPS
    text = normalize_text(text)
    found = []
    
    # Сортируем группы по длине в обратном порядке, чтобы сначала проверять более длинные
    sorted_groups = sorted(group_list, key=len, reverse=True)
    
    # Создаём временную копию текста для маркировки уже найденных групп
    temp_text = text
    
    for g in sorted_groups:
        escaped = re.escape(g)
        # Ищем группу как отдельное слово с границами слова
        pattern_word = r'(?:^|(?<![А-Яа-яA-Za-z0-9-]))' + escaped + r'(?:$|(?![А-Яа-яA-Za-z0-9-]))'
        
        if re.search(pattern_word, temp_text, re.IGNORECASE):
            found.append(g)
            # Заменяем найденную группу в temp_text на маркер, чтобы не находить её снова как часть другой
            temp_text = re.sub(pattern_word, '<<FOUND>>', temp_text, flags=re.IGNORECASE)
        else:
            # Если не нашли как отдельное слово, проверяем, не является ли это частью другой группы
            # Но только если группа не является подстрокой уже найденной группы
            is_substring_of_found = False
            for existing in found:
                if g in existing or existing in g:
                    # Если группы частично совпадают, проверяем, не является ли одна частью другой
                    if g in existing:
                        # Текущая группа - подстрока уже найденной, пропускаем
                        is_substring_of_found = True
                        break
                    elif existing in g:
                        # Текущая группа содержит найденную, но мы уже проверили более длинные группы первыми
                        # Поэтому это не должно произойти при правильной сортировке
                        pass
            
            if not is_substring_of_found and re.search(escaped, text, re.IGNORECASE):
                # Проверяем, не является ли это частью слова (например, "И-25" в "ОПИ-25")
                # Ищем позицию вхождения
                match = re.search(escaped, text, re.IGNORECASE)
                if match:
                    start_pos = match.start()
                    end_pos = match.end()
                    # Проверяем, не является ли найденное частью более длинной группы
                    is_part_of_larger = False
                    for longer_group in sorted_groups:
                        if longer_group != g and len(longer_group) > len(g):
                            # Ищем более длинную группу в тексте
                            longer_match = re.search(re.escape(longer_group), text, re.IGNORECASE)
                            if longer_match:
                                longer_start = longer_match.start()
                                longer_end = longer_match.end()
                                # Если текущая группа находится внутри более длинной
                                if longer_start <= start_pos and longer_end >= end_pos:
                                    is_part_of_larger = True
                                    break
                    if not is_part_of_larger:
                        found.append(g)
    
    # Удаляем дубликаты, сохраняя порядок
    seen = set()
    unique_found = []
    for g in found:
        if g not in seen:
            seen.add(g)
            unique_found.append(g)
    
    return unique_found

def best_photo_url(photo):
    if 'orig_photo' in photo:
        return photo['orig_photo']['url']
    sizes = photo.get('sizes', [])
    if not sizes:
        return None
    best = max(sizes, key=lambda s: s['height'] * s['width'])
    return best['url']

def download_photo(url, path):
    try:
        r = requests.get(url, stream=True, timeout=10)
        if r.status_code != 200:
            return False
        with open(path, 'wb') as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
        return True
    except Exception:
        return False

import subprocess

def ocr_image_tesseract(image_path):
    try:
        # Используем subprocess вместо pytesseract
        cmd = [
            r'C:\Users\неликаеванс\Desktop\Test\Nina Parsing\Tesseract\tesseract.exe',
            image_path,
            'stdout',  # вывод в консоль
            '-l', 'rus',
            '--tessdata-dir', r'C:\Users\неликаеванс\Desktop\Test\Nina Parsing\Tesseract\tessdata',
            '--psm', '6'
        ]
        
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        
        # Пробуем декодировать в cp1251
        try:
            text = result.stdout.decode('cp1251').strip()
        except:
            try:
                text = result.stdout.decode('windows-1251').strip()
            except:
                text = result.stdout.decode('utf-8', errors='replace').strip()
        
        return text
    except Exception as e:
        print(f"Ошибка OCR для {image_path}: {e}")
        return ""

def parse_event_date(text, post_date):
    MONTHS = {'января':1,'февраля':2,'марта':3,'апреля':4,'мая':5,'июня':6,
              'июля':7,'августа':8,'сентября':9,'октября':10,'ноября':11,'декабря':12}
    MONTHS_NOM = {'январь':1,'февраль':2,'март':3,'апрель':4,'май':5,'июнь':6,
                  'июль':7,'август':8,'сентябрь':9,'октябрь':10,'ноябрь':11,'декабрь':12}
    t = text.lower()
    if re.search(r'сегодня|в этот день', t):
        return post_date.strftime('%Y-%m-%d')
    match_full = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', t)
    if match_full:
        day, month, year = map(int, match_full.groups())
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            pass
    match_short = re.search(r'(\d{1,2})\.(\d{1,2})(?![\.\d])', t)
    if match_short:
        day, month = map(int, match_short.groups())
        year = post_date.year
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            pass
    match_month = re.search(r'(\d{1,2})\s+(' + '|'.join(MONTHS.keys()) + ')', t)
    if match_month:
        day = int(match_month.group(1))
        month_name = match_month.group(2)
        month = MONTHS[month_name]
        year = post_date.year
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            return None
    match_month_nom = re.search(r'(\d{1,2})\s+(' + '|'.join(MONTHS_NOM.keys()) + ')', t)
    if match_month_nom:
        day = int(match_month_nom.group(1))
        month_name = match_month_nom.group(2)
        month = MONTHS_NOM[month_name]
        year = post_date.year
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            return None
    return None

def take_posts_date_range(domain, token, start_date, end_date, max_posts=150, early_start=None):
    offset = 0
    collected = []
    per_request = 100
    start_ts = int(start_date.timestamp())
    end_ts = int(end_date.timestamp()) + 86399
    early_ts = int(early_start.timestamp()) if early_start else start_ts

    while len(collected) < max_posts:
        try:
            response = requests.get('https://api.vk.com/method/wall.get', params={
                'access_token': token,
                'v': VERSION,
                'domain': domain,
                'count': per_request,
                'offset': offset
            })
            data = response.json()
            items = data.get('response', {}).get('items', [])
            if not items:
                break

            for post in items:
                post_ts = post['date']
                if post_ts < early_ts:
                    return collected
                if post_ts > end_ts:
                    continue

                if early_ts <= post_ts < start_ts:
                    txt = post.get('text', '').strip()
                    attachments = post.get('attachments', [])
                    photos = [att for att in attachments if att['type'] == 'photo']
                    if len(photos) == 1 and (not txt or len(txt) <= 40):
                        collected.append(post)
                elif post_ts >= start_ts:
                    collected.append(post)

                if len(collected) >= max_posts:
                    return collected

            offset += per_request
            time.sleep(0.3)
        except Exception as e:
            print(f"Ошибка при запросе к VK: {e}")
            break
    return collected

def extract_text_from_post(post):
    texts = []
    if post.get('text'):
        texts.append(post['text'])
    for copied in post.get('copy_history', []):
        if copied.get('text'):
            texts.append(f"[Репост: {copied['text']}]")
    return ' '.join(texts)

def extract_attachments(post):
    attachments = []
    attachments.extend(post.get('attachments', []))
    for copied in post.get('copy_history', []):
        attachments.extend(copied.get('attachments', []))
    return attachments

def process_post(post, img_dir, selected_group=None):
    is_reposted = bool(post.get('copy_history'))
    txt = extract_text_from_post(post)
    post_date = datetime.fromtimestamp(post['date'])
    event_date = parse_event_date(txt, post_date) if txt else None
    final_date = event_date if event_date else post_date.strftime('%Y-%m-%d')

    attachments = extract_attachments(post)
    photos = [att for att in attachments if att['type'] == 'photo']
    has_single_photo = len(photos) == 1
    txt_len = len(txt)

    is_flyer = has_single_photo and (txt_len == 0 or txt_len <= 40)

    # Общая функция для проверки, нужно ли отклонить пост
    def should_reject(groups_list):
        if not selected_group:          # группа не выбрана – всё принимаем
            return False
        if not groups_list:             # нет групп – принимаем (пользователь сам отфильтрует)
            return False
        if selected_group in groups_list:
            return False                # группа найдена – принимаем
        return True                     # есть группы, но нужной нет – отклоняем

    if is_flyer:
        photo = photos[0]['photo']
        photo_url = best_photo_url(photo)
        if not photo_url:
            return None

        filename = f"{final_date}_{post['owner_id']}_{post['id']}.jpg"
        path = os.path.join(img_dir, filename)

        if download_photo(photo_url, path):
            ocr_text = ocr_image_tesseract(path)
            groups_from_photo = find_groups(ocr_text) if ocr_text else []
            if should_reject(groups_from_photo):
                os.remove(path)
                return None
            return {
                'body': txt,
                'url': f"https://vk.com/wall{post['owner_id']}_{post['id']}",
                'date': final_date,
                'groups': groups_from_photo,
                'photo_path': path,
                'is_reposted': is_reposted
            }
        else:
            return None
    else:
        groups_from_text = find_groups(txt) if txt else []
        if should_reject(groups_from_text):
            return None
        return {
            'body': txt,
            'url': f"https://vk.com/wall{post['owner_id']}_{post['id']}",
            'date': final_date,
            'groups': groups_from_text,
            'photo_path': None,
            'is_reposted': is_reposted
        }

def filter_by_date_range(data, start_date, end_date, date_field='date'):
    filtered = []
    start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
    for item in data:
        try:
            item_date = datetime.strptime(item[date_field], '%Y-%m-%d').date()
            if start_dt <= item_date <= end_dt:
                filtered.append(item)
        except (KeyError, ValueError):
            continue
    return filtered

def parse_gigachat_response(content):
    events = []
    lines = content.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split('|')
        if len(parts) >= 4:
            name = parts[0].strip()
            description = parts[1].strip()
            location = parts[2].strip()
            groups_str = parts[3].strip()
            groups = [g.strip() for g in groups_str.split(',') if g.strip()]
            events.append({
                'name': name,
                'description': description,
                'location': location,
                'groups': groups
            })
        else:
            print(f"Не удалось распарсить строку: {line}")
    return events

def extract_domain_from_url(text):
    text = text.strip()
    match = re.search(r'(?:https?://)?(?:www\.)?vk\.com/([a-zA-Z0-9_.-]+)', text)
    if match:
        return match.group(1)
    return text

# ------------------ Диалог добавления домена ------------------
class AddDomainDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить группу")
        self.setModal(True)
        self.setFixedSize(400, 120)
        layout = QVBoxLayout()
        label = QLabel("Вставьте ссылку на группу ВК или домен:")
        layout.addWidget(label)
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText("например, https://vk.com/zhgmk_professionalitet")
        layout.addWidget(self.line_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def get_domain(self):
        raw = self.line_edit.text().strip()
        return extract_domain_from_url(raw)

# ------------------ Рабочий поток для сбора постов ------------------
class Worker(QObject):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int, int)

    def __init__(self, domain, token, start_date, end_date, selected_group, max_posts, additional_domains):
        super().__init__()
        self.domain = domain
        self.token = token
        self.start_date = start_date
        self.end_date = end_date
        self.selected_group = selected_group
        self.max_posts = max_posts
        self.additional_domains = additional_domains

    def run(self):
        import datetime
        import time
        import json
        import os
        from datetime import timedelta

        debug_log = open('scan_debug.log', 'w', encoding='utf-8')
        try:
            start = datetime.datetime.strptime(self.start_date, '%Y-%m-%d')
            end = datetime.datetime.strptime(self.end_date, '%Y-%m-%d')
            early_start = start - timedelta(days=7)
        except ValueError:
            self.finished.emit({'error': 'Неверный формат даты. Используйте ГГГГ-ММ-ДД.'})
            debug_log.close()
            return

        if (end - start) > timedelta(days=60):
            self.finished.emit({'error': 'Период не должен превышать 2 месяца.'})
            debug_log.close()
            return

        all_results = []
        domains_to_scan = [self.domain] + self.additional_domains
        self.progress.emit(f"Будут сканироваться домены: {domains_to_scan}")
        debug_log.write(f"Домены для сканирования: {domains_to_scan}\n")
        debug_log.write(f"Выбранная группа для фильтрации: {self.selected_group}\n")

        os.makedirs('rawImages', exist_ok=True)

        total_domains = len(domains_to_scan)
        for idx_dom, dom in enumerate(domains_to_scan):
            if not dom:
                continue
            self.progress.emit(f"Сканирование домена: {dom}")
            debug_log.write(f"\n=== Сканирование домена: {dom} ===\n")
            posts = take_posts_date_range(dom, self.token, start, end, max_posts=self.max_posts, early_start=early_start)
            self.progress.emit(f"Домен {dom}: собрано {len(posts)} постов")
            debug_log.write(f"Получено постов от API: {len(posts)}\n")

            for i, post in enumerate(posts):
                debug_log.write(f"\n--- Пост #{i+1} из домена {dom} ---\n")
                post_text = post.get('text', '')
                debug_log.write(f"Текст: {post_text[:300]}\n")
                debug_log.write(f"Дата поста (timestamp): {post.get('date')}\n")

                # ✅ Используем выбранную группу для фильтрации
                r = process_post(post, 'rawImages', self.selected_group)
                if r:
                    debug_log.write(f">>> ПРИНЯТ, группы: {r.get('groups')}\n")
                    r['source_domain'] = dom
                    all_results.append(r)
                else:
                    debug_log.write(f">>> ОТКЛОНЁН (process_post вернул None)\n")

                progress_value = idx_dom * len(posts) + i + 1
                progress_max = total_domains * self.max_posts
                self.progress_value.emit(progress_value, progress_max)

        filtered_results = all_results
        debug_log.write(f"\nВсего собрано записей до фильтрации по датам: {len(all_results)}\n")
        debug_log.write(f"После фильтрации по датам: {len(filtered_results)}\n")

        output_file = 'posts.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(filtered_results, f, ensure_ascii=False, indent=2)

        debug_log.close()
        self.finished.emit({'success': True, 'count': len(filtered_results), 'file': output_file})

# ------------------ Рабочий поток для анализа изображений через GigaChat ------------------
class AnalysisWorker(QObject):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int, int)

    def __init__(self, raw_folder, complete_folder, credentials, scope, model, start_date, end_date):
        super().__init__()
        self.raw_folder = raw_folder
        self.complete_folder = complete_folder
        self.credentials = credentials
        self.scope = scope
        self.model = model
        self.start_date = start_date
        self.end_date = end_date
        self.com_folder = complete_folder

    def run(self):
        try:
            os.makedirs(self.com_folder, exist_ok=True)

            processed_files = set(os.listdir(self.complete_folder))
            all_raw = [f for f in os.listdir(self.raw_folder) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            new_files = [f for f in all_raw if f not in processed_files]

            if not new_files:
                self.finished.emit({'error': 'Нет новых изображений для анализа.'})
                return

            self.progress.emit(f"Новых изображений для анализа: {len(new_files)}")
            self.progress_value.emit(0, len(new_files))

            events_path = 'events.json'
            if os.path.exists(events_path):
                with open(events_path, 'r', encoding='utf-8') as f:
                    existing_events = json.load(f)
            else:
                existing_events = []

            client = GigaChat(
                credentials=self.credentials,
                scope=self.scope,
                verify_ssl_certs=False,
                timeout=600,
                model=self.model
            )
            self.progress.emit(f"Клиент GigaChat создан (модель: {self.model})")

            new_events = []
            successful_files = []

            for idx, filename in enumerate(new_files, 1):
                img_path = os.path.join(self.raw_folder, filename)
                self.progress.emit(f"Обрабатываю {idx}/{len(new_files)}: {filename}")
                self.progress_value.emit(idx, len(new_files))

                # Повторные попытки для текущего файла
                max_retries = 3
                success = False
                for attempt in range(max_retries):
                    try:
                        # Загружаем файл
                        with open(img_path, "rb") as f:
                            file_info = client.upload_file(f)

                        prompt = (
                            "Ты получаешь изображение с расписанием мероприятий. "
                            "Для каждого мероприятия на изображении выведи одну строку в формате:\n"
                            "Название | Описание | Место проведения | Группы\n"
                            "где группы перечислены через запятую.\n"
                            "Пример:\n"
                            "Интерактивная викторина | Интерактивная викторина 'До дна пишешь' в читальном зале. | читальный зал | ПД-23-2, И-23, ПД-23\n"
                            "Если место не указано, впиши что-то подходящее по смыслу (колледж, территория колледжа и т.д.). "
                            "Если групп несколько, перечисли их через запятую. Если группа не указана, оставь поле пустым.\n"
                            "Не добавляй никаких пояснений, только строки в указанном формате, по одному мероприятию на строку."
                        )

                        response = client.chat(
                            Chat(
                                messages=[
                                    Messages(
                                        role=MessagesRole.USER,
                                        content=prompt,
                                        attachments=[file_info.id_]
                                    )
                                ],
                                temperature=0.1,
                            )
                        )

                        content = response.choices[0].message.content.strip()
                        log_gigachat_response(content, context=f"Image: {filename}")
                        if content.startswith("```"):
                            content = content.split('\n', 1)[-1] if '\n' in content else content[3:]
                        if content.endswith("```"):
                            content = content.rsplit('\n', 1)[0] if '\n' in content else content[:-3]
                        content = content.strip()

                        events_from_image = parse_gigachat_response(content)

                        # Дедупликация внутри одного изображения (по названию и описанию)
                        unique_events = []
                        seen_keys = set()
                        for ev in events_from_image:
                            key = (ev['name'], ev['description'])
                            if key not in seen_keys:
                                seen_keys.add(key)
                                unique_events.append(ev)

                        if unique_events:
                            try:
                                date_part = filename.split('_')[0]
                                datetime.strptime(date_part, '%Y-%m-%d')
                            except:
                                date_part = datetime.now().strftime('%Y-%m-%d')

                            parts = filename.split('_')
                            if len(parts) >= 3:
                                owner_id = parts[1]
                                post_id = parts[2].split('.')[0]
                                post_url = f"https://vk.com/wall{owner_id}_{post_id}"
                            else:
                                post_url = "Соцсети колледжа"

                            for ev in unique_events:
                                ev['date'] = date_part
                                ev['source_image'] = filename
                                ev['url'] = post_url
                            new_events.extend(unique_events)

                        success = True
                        successful_files.append(filename)
                        break  # успешно обработано, выходим из цикла retry

                    except Exception as e:
                        error_msg = str(e)
                        self.progress.emit(f"Ошибка при обработке {filename} (попытка {attempt+1}/{max_retries}): {error_msg}")
                        if attempt == max_retries - 1:
                            self.progress.emit(f"Не удалось обработать {filename} после {max_retries} попыток")
                        else:
                            wait_time = 2 ** attempt
                            time.sleep(wait_time)

                # Если файл успешно обработан, перемещаем его в complete_folder
                if success:
                    dest_path = os.path.join(self.complete_folder, filename)
                    shutil.move(img_path, dest_path)

            client.close()

            # Сохраняем события
            combined_events = existing_events + new_events
            filtered_events = filter_by_date_range(combined_events, self.start_date, self.end_date)

            with open(events_path, 'w', encoding='utf-8') as f:
                json.dump(filtered_events, f, ensure_ascii=False, indent=2)

            self.progress.emit(f"Готово! Обработано {len(successful_files)}/{len(new_files)} изображений. Результат сохранён в {events_path}")
            self.finished.emit({'success': True, 'file': events_path, 'count_events': len(filtered_events)})

        except Exception as e:
            self.finished.emit({'error': str(e)})

# ------------------ Главное окно ------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nexus")
        self.setGeometry(100, 100, 1200, 800)
        self.setStyleSheet(self.get_stylesheet())

        self.additional_domains = []
        self.settings = QSettings("config.ini", QSettings.Format.IniFormat)

        self.has_images_for_analysis = False

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        header = QLabel("Nexus")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        header.setStyleSheet("color: white;")
        main_layout.addWidget(header)

        # Горизонтальный контейнер для двух колонок
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(20)
        main_layout.addLayout(columns_layout)

        # Левая колонка
        left_column = QFrame()
        left_column.setFrameShape(QFrame.Shape.NoFrame)
        left_layout = QVBoxLayout(left_column)
        left_layout.setSpacing(15)

        # --- Блок VK ---
        vk_frame = QFrame()
        vk_frame.setObjectName("vk_frame")
        vk_frame.setStyleSheet("""
            QFrame#vk_frame {
                border: 2px solid #00c853;
                border-radius: 10px;
                padding: 10px;
                background-color: #1e1e1e;
            }
        """)
        vk_layout = QVBoxLayout(vk_frame)

        self.domain_edit = self.create_line_edit("zhgmk_professionalitet")
        vk_layout.addWidget(self.create_labeled_widget("Ссылка/домен:", self.domain_edit))

        self.token_edit = self.create_line_edit("", password=True)
        vk_layout.addWidget(self.create_labeled_widget("Token VK:", self.token_edit))

        self.group_combo = QComboBox()
        self.group_combo.addItem("")
        self.group_combo.addItems(GROUPS)
        self.group_combo.setEditable(True)
        self.group_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.group_combo.setStyleSheet(self.get_combo_style("#00c853"))
        vk_layout.addWidget(self.create_labeled_widget("Группа:", self.group_combo))

        # Дата
        date_layout = QHBoxLayout()
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setDate(QDate.currentDate())
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setStyleSheet(self.get_date_edit_style())
        date_layout.addWidget(self.start_date_edit)

        separator = QLabel("-")
        separator.setStyleSheet("color: white; font-size: 16pt;")
        separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        date_layout.addWidget(separator)

        self.end_date_edit = QDateEdit()
        self.end_date_edit.setDate(QDate.currentDate())
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setStyleSheet(self.get_date_edit_style())
        date_layout.addWidget(self.end_date_edit)

        vk_layout.addWidget(self.create_labeled_widget("Даты:", date_layout))

        # Макс. постов
        self.max_posts_spin = QSpinBox()
        self.max_posts_spin.setRange(1, 500)
        self.max_posts_spin.setValue(150)
        self.max_posts_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2f2f2f;
                color: white;
                border: 2px solid #00c853;
                border-radius: 5px;
                padding: 5px;
                font-size: 12pt;
            }
        """)
        vk_layout.addWidget(self.create_labeled_widget("Макс. постов:", self.max_posts_spin))

        left_layout.addWidget(vk_frame)

        # --- Блок GigaChat ---
        giga_frame = QFrame()
        giga_frame.setObjectName("giga_frame")
        giga_frame.setStyleSheet("""
            QFrame#giga_frame {
                border: 2px solid #ff6e6e;
                border-radius: 10px;
                padding: 10px;
                background-color: #1e1e1e;
            }
        """)
        giga_layout = QVBoxLayout(giga_frame)

        self.credentials_edit = self.create_line_edit("", password=True)
        giga_layout.addWidget(self.create_labeled_widget("GigaChat Credentials:", self.credentials_edit))

        self.scope_edit = self.create_line_edit("GIGACHAT_API_PERS")
        giga_layout.addWidget(self.create_labeled_widget("Scope:", self.scope_edit))

        self.model_combo = QComboBox()
        self.model_combo.addItems(["GigaChat-2", "GigaChat-2-Max", "GigaChat-2-Pro"])
        self.model_combo.setEditable(True)
        self.model_combo.setStyleSheet(self.get_combo_style("#ff6e6e"))
        giga_layout.addWidget(self.create_labeled_widget("Модель:", self.model_combo))

        left_layout.addWidget(giga_frame)

        # Кнопки
        buttons_layout = QHBoxLayout()
        self.scan_button = self.create_button("Сканировать посты", self.start_scan)
        buttons_layout.addWidget(self.scan_button)

        self.analyze_button = self.create_button("Анализ модели", self.start_analysis)
        self.analyze_button.setEnabled(False)
        buttons_layout.addWidget(self.analyze_button)

        self.doc_button = self.create_button("Создать документ", self.create_document)
        self.doc_button.setEnabled(os.path.exists('selected_items.json'))  # активируем, если есть файл
        buttons_layout.addWidget(self.doc_button)

        self.show_posts_button = self.create_button("Выбрать посты", self.show_posts_list)
        buttons_layout.addWidget(self.show_posts_button)

        left_layout.addLayout(buttons_layout)
        left_layout.addStretch()

        columns_layout.addWidget(left_column, 45)

        # Правая колонка (дополнительные группы)
        right_column = QFrame()
        right_column.setObjectName("right_column")
        right_column.setStyleSheet("""
            QFrame#right_column {
                border: 2px solid white;
                border-radius: 10px;
                background-color: #1a1a1a;
            }
        """)
        right_layout = QVBoxLayout(right_column)

        header_panel = QWidget()
        header_layout = QHBoxLayout(header_panel)
        header_layout.setContentsMargins(0, 0, 0, 0)

        panel_title = QLabel("Дополнительные группы")
        panel_title.setStyleSheet("color: white; font-size: 14pt; font-weight: bold;")
        header_layout.addWidget(panel_title)

        self.add_domain_button = QPushButton("+")
        self.add_domain_button.setFixedSize(30, 30)
        self.add_domain_button.setStyleSheet("""
            QPushButton {
                background-color: #00c853;
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 16pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00e676;
            }
        """)
        self.add_domain_button.clicked.connect(self.add_domain)
        header_layout.addWidget(self.add_domain_button)

        right_layout.addWidget(header_panel)

        self.domains_list = QListWidget()
        self.domains_list.setStyleSheet("""
            QListWidget {
                background-color: #2f2f2f;
                color: white;
                border: 1px solid #00c853;
                border-radius: 5px;
                font-size: 12pt;
            }
            QListWidget::item {
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #00c853;
                border-radius: 3px;
            }
        """)
        right_layout.addWidget(self.domains_list)

        columns_layout.addWidget(right_column, 45)

        # Нижняя панель: прогресс-бар и лог
        bottom_panel = QWidget()
        bottom_layout = QVBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(0, 10, 0, 0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #00c853;
                border-radius: 5px;
                text-align: center;
                color: white;
                background-color: #2f2f2f;
            }
            QProgressBar::chunk {
                background-color: #00c853;
                border-radius: 3px;
            }
        """)
        bottom_layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #00c853;
                border: 2px solid #00c853;
                border-radius: 5px;
                font-family: monospace;
                font-size: 11pt;
            }
        """)
        bottom_layout.addWidget(self.log_text)

        main_layout.addWidget(bottom_panel)

        # Статус бар
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet("color: #00c853; background-color: #0f0f0f;")

        self.load_config()
        self.check_and_enable_analysis_button()
        

    # ------------------ Вспомогательные методы для стилей ------------------
    def get_stylesheet(self):
        return """
            QMainWindow {
                background-color: #0f0f0f;
            }
            QLabel {
                color: white;
                font-size: 12pt;
            }
            QLineEdit {
                background-color: #2f2f2f;
                color: white;
                border: 2px solid #00c853;
                border-radius: 5px;
                padding: 5px;
                font-size: 12pt;
            }
            QLineEdit:focus {
                border: 2px solid #ff6e6e;
            }
            QPushButton {
                background-color: #0f0f0f;
                color: white;
                border: 2px solid #ff6e6e;
                border-radius: 5px;
                padding: 10px 20px;
                font-size: 12pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff6e6e;
                color: black;
            }
            QPushButton:pressed {
                background-color: #ff4444;
            }
            QPushButton:disabled {
                border-color: gray;
                color: gray;
            }
            /* Стили для QMessageBox */
            QMessageBox {
                background-color: #2f2f2f;
                color: white;
            }
            QMessageBox QLabel {
                color: white;
                background-color: transparent;
            }
            QMessageBox QPushButton {
                background-color: #0f0f0f;
                color: white;
                border: 2px solid #ff6e6e;
                padding: 5px 15px;
                min-width: 80px;
            }
            QMessageBox QPushButton:hover {
                background-color: #ff6e6e;
                color: black;
            }
        """

    def get_combo_style(self, color):
        return f"""
            QComboBox {{
                background-color: #2f2f2f;
                color: white;
                border: 2px solid {color};
                border-radius: 5px;
                padding: 5px;
                font-size: 12pt;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border-left-width: 1px;
                border-left-color: {color};
                border-left-style: solid;
                border-top-right-radius: 5px;
                border-bottom-right-radius: 5px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {color};
                width: 0px;
                height: 0px;
                margin-right: 5px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #2f2f2f;
                color: white;
                selection-background-color: {color};
                border-radius: 5px;
            }}
        """

    def get_date_edit_style(self):
        return """
            QDateEdit {
                background-color: #2f2f2f;
                color: white;
                border: 2px solid #00c853;
                border-radius: 5px;
                padding: 5px;
                font-size: 12pt;
            }
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border-left-width: 1px;
                border-left-color: #00c853;
                border-left-style: solid;
                border-top-right-radius: 5px;
                border-bottom-right-radius: 5px;
            }
            QDateEdit::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #00c853;
                width: 0px;
                height: 0px;
                margin-right: 5px;
            }
            QCalendarWidget QWidget {
                background-color: #2f2f2f;
                color: white;
            }
        """

    def create_line_edit(self, text, password=False):
        edit = QLineEdit()
        edit.setText(text)
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        return edit

    def create_labeled_widget(self, label_text, widget):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setFixedWidth(160)
        layout.addWidget(label)
        if isinstance(widget, QLayout):
            layout.addLayout(widget)
        else:
            layout.addWidget(widget)
        return container

    def create_button(self, text, callback):
        btn = QPushButton(text)
        btn.clicked.connect(callback)
        return btn
    
    def check_and_enable_analysis_button(self):
        """Проверяет наличие изображений в rawImages и активирует кнопку анализа."""
        if os.path.exists('rawImages'):
            images = [f for f in os.listdir('rawImages') if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            has_images = len(images) > 0
        else:
            has_images = False
        self.analyze_button.setEnabled(has_images)
        if has_images:
            self.log("Найдены существующие изображения. Можно запустить анализ.")
        else:
            self.log("Нет изображений для анализа. Выполните сканирование или добавьте файлы в rawImages вручную.")
        return has_images

    # ------------------ Обработчики событий ------------------
    def add_domain(self):
        dialog = AddDomainDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            domain = dialog.get_domain()
            if domain and domain not in self.additional_domains:
                self.additional_domains.append(domain)
                self.domains_list.addItem(domain)
                self.save_config()

    def log(self, message):
        self.log_text.append(message)
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)

    def update_progress(self, value, maximum):
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)

    # ------------------ Сохранение/загрузка конфигурации ------------------
    def save_config(self):
        self.settings.setValue("domain", self.domain_edit.text())
        self.settings.setValue("token", self.token_edit.text())
        self.settings.setValue("group", self.group_combo.currentText())
        self.settings.setValue("start_date", self.start_date_edit.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("end_date", self.end_date_edit.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("max_posts", self.max_posts_spin.value())
        self.settings.setValue("additional_domains", json.dumps(self.additional_domains))

        # GigaChat
        self.settings.setValue("giga_credentials", self.credentials_edit.text())
        self.settings.setValue("giga_scope", self.scope_edit.text())
        self.settings.setValue("giga_model", self.model_combo.currentText())

    def load_config(self):
        self.domain_edit.setText(self.settings.value("domain", "zhgmk_professionalitet"))
        self.token_edit.setText(self.settings.value("token", ""))
        self.group_combo.setCurrentText(self.settings.value("group", ""))
        start_date_str = self.settings.value("start_date", QDate.currentDate().toString(Qt.DateFormat.ISODate))
        self.start_date_edit.setDate(QDate.fromString(start_date_str, Qt.DateFormat.ISODate))
        end_date_str = self.settings.value("end_date", QDate.currentDate().toString(Qt.DateFormat.ISODate))
        self.end_date_edit.setDate(QDate.fromString(end_date_str, Qt.DateFormat.ISODate))
        self.max_posts_spin.setValue(int(self.settings.value("max_posts", 150)))
        additional_domains_json = self.settings.value("additional_domains", "[]")
        try:
            self.additional_domains = json.loads(additional_domains_json)
        except:
            self.additional_domains = []
        self.domains_list.clear()
        for dom in self.additional_domains:
            self.domains_list.addItem(dom)

        # GigaChat
        self.credentials_edit.setText(self.settings.value("giga_credentials", ""))
        self.scope_edit.setText(self.settings.value("giga_scope", "GIGACHAT_API_PERS"))
        self.model_combo.setCurrentText(self.settings.value("giga_model", "GigaChat-2"))

    # ------------------ Сканирование постов ------------------
    def start_scan(self):
        # Удаляем временные файлы перед новым сканированием
        for f in ['posts.json', 'selected_items.json', 'doc.json']:
            if os.path.exists(f):
                os.remove(f)

        self.save_config()

        self.scan_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.doc_button.setEnabled(False)
        self.status_bar.showMessage("Сканирование...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()

        raw_domain = self.domain_edit.text().strip()
        domain = extract_domain_from_url(raw_domain)
        token = self.token_edit.text().strip()
        group = self.group_combo.currentText().strip()
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        max_posts = self.max_posts_spin.value()

        if not token:
            QMessageBox.critical(self, "Ошибка", "Необходимо указать токен VK")
            self.scan_button.setEnabled(True)
            self.status_bar.showMessage("Готов")
            self.progress_bar.setVisible(False)
            return

        if not domain:
            QMessageBox.critical(self, "Ошибка", "Необходимо указать домен или ссылку на группу")
            self.scan_button.setEnabled(True)
            self.status_bar.showMessage("Готов")
            self.progress_bar.setVisible(False)
            return

        self.thread = QThread()
        self.worker = Worker(domain, token, start_date, end_date, group, max_posts, self.additional_domains)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_scan_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.status_bar.showMessage)
        self.worker.progress_value.connect(self.update_progress)

        self.thread.start()

    def on_scan_finished(self, result):
        self.scan_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        if 'error' in result:
            QMessageBox.critical(self, "Ошибка", result['error'])
            self.status_bar.showMessage("Ошибка")
            self.has_images_for_analysis = False
        else:
            QMessageBox.information(self, "Успех",
                                   f"Собрано записей: {result['count']}\nРезультат сохранён в {result['file']}")
            self.status_bar.showMessage("Сканирование завершено")

            if os.path.exists('rawImages'):
                images = [f for f in os.listdir('rawImages') if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                self.has_images_for_analysis = len(images) > 0
            else:
                self.has_images_for_analysis = False

            if self.has_images_for_analysis:
                self.analyze_button.setEnabled(True)
                self.log("Найдены изображения для анализа. Нажмите «Анализ модели».")
            else:
                self.analyze_button.setEnabled(False)
                self.log("Нет изображений для анализа.")

    # ------------------ Анализ изображений ------------------
    def start_analysis(self):
        self.save_config()

        credentials = self.credentials_edit.text().strip()
        scope = self.scope_edit.text().strip()
        model = self.model_combo.currentText().strip()
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")

        if not credentials:
            QMessageBox.critical(self, "Ошибка", "Не указаны GigaChat Credentials")
            return
        if not scope:
            scope = "GIGACHAT_API_PERS"

        if not os.path.exists('rawImages'):
            QMessageBox.critical(self, "Ошибка", "Папка rawImages не найдена. Сначала выполните сканирование.")
            return

        self.analyze_button.setEnabled(False)
        self.doc_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        self.status_bar.showMessage("Анализ изображений...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log("Запуск анализа через GigaChat Vision...")

        self.analysis_thread = QThread()
        self.analysis_worker = AnalysisWorker('rawImages', 'scanComplete', credentials, scope, model, start_date, end_date)
        self.analysis_worker.moveToThread(self.analysis_thread)
        self.analysis_thread.started.connect(self.analysis_worker.run)
        self.analysis_worker.finished.connect(self.on_analysis_finished)
        self.analysis_worker.finished.connect(self.analysis_thread.quit)
        self.analysis_worker.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_thread.finished.connect(self.analysis_thread.deleteLater)
        self.analysis_worker.progress.connect(self.log)
        self.analysis_worker.progress_value.connect(self.update_progress)

        self.analysis_thread.start()

    def on_analysis_finished(self, result):
        self.scan_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        if 'error' in result:
            QMessageBox.critical(self, "Ошибка", f"Ошибка анализа:\n{result['error']}")
            self.status_bar.showMessage("Ошибка анализа")
            self.log(f"Ошибка: {result['error']}")
        else:
            QMessageBox.information(self, "Успех",
                                   f"Анализ завершён. Найдено событий: {result.get('count_events', 0)}\nРезультат сохранён в {result['file']}")
            self.status_bar.showMessage("Анализ завершён")
            self.log(f"Анализ завершён. Файл: {result['file']}")
            # После анализа кнопка создания документа не активируется автоматически,
            # пользователь должен выбрать посты вручную.

    # ------------------ Выбор постов ------------------
    def show_posts_list(self):
        posts = []
        events = []
        if os.path.exists('posts.json'):
            try:
                with open('posts.json', 'r', encoding='utf-8') as f:
                    posts = json.load(f)
            except:
                pass
        if os.path.exists('events.json'):
            try:
                with open('events.json', 'r', encoding='utf-8') as f:
                    events = json.load(f)
            except:
                pass

        self.posts_window = PostsListWindow(posts, events, self)
        self.posts_window.saved.connect(self.enable_doc_button)
        self.posts_window.show()

    def enable_doc_button(self):
        self.doc_button.setEnabled(True)

    # ------------------ Создание документа Word ------------------
    def get_month_name(self):
        """Возвращает название месяца в родительном падеже из выбранной начальной даты."""
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        month_num = int(start_date.split('-')[1])
        months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        return months[month_num - 1]

    def generate_docx_from_file(self, json_path):
        """Создаёт документ Word из JSON-файла с мероприятиями."""
        try:
            month_name = self.get_month_name()
            create_document_from_json(json_path, "output.docx", month_name=month_name, teacher_count="_____")
            QMessageBox.information(self, "Успех", "Документ Word создан: output.docx")
            self.status_bar.showMessage("Документ создан")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать документ Word: {str(e)}")

    def create_document(self):
        """Обработчик кнопки 'Создать документ'."""
        if not os.path.exists('selected_items.json'):
            QMessageBox.warning(self, "Предупреждение",
                               "Сначала выберите посты в окне «Выбрать посты» и нажмите «Сохранить».")
            return

        # Если есть doc.json, используем его напрямую для генерации Word
        if os.path.exists('doc.json'):
            self.generate_docx_from_file('doc.json')
            return

        # Иначе запускаем DocumentCreator для генерации doc.json
        credentials = self.credentials_edit.text().strip()
        scope = self.scope_edit.text().strip() or "GIGACHAT_API_PERS"
        model = "GigaChat-2"

        if not credentials:
            QMessageBox.critical(self, "Ошибка", "Не указаны GigaChat Credentials")
            return

        self.doc_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.status_bar.showMessage("Создание документа через GigaChat...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log("Запуск создания документа через GigaChat...")

        self.doc_thread = QThread()
        self.doc_worker = DocumentCreator('selected_items.json', credentials, scope, model)
        self.doc_worker.moveToThread(self.doc_thread)
        self.doc_thread.started.connect(self.doc_worker.run)
        self.doc_worker.finished.connect(self.on_document_created)
        self.doc_worker.finished.connect(self.doc_thread.quit)
        self.doc_worker.finished.connect(self.doc_worker.deleteLater)
        self.doc_thread.finished.connect(self.doc_thread.deleteLater)
        self.doc_worker.progress.connect(self.log)
        self.doc_worker.progress_value.connect(self.update_progress)

        self.doc_thread.start()

    def on_document_created(self, result):
        self.scan_button.setEnabled(True)
        self.analyze_button.setEnabled(self.has_images_for_analysis)
        self.doc_button.setEnabled(True)  # selected_items.json существует
        self.progress_bar.setVisible(False)

        if 'error' in result:
            QMessageBox.critical(self, "Ошибка", f"Ошибка создания документа:\n{result['error']}")
            self.status_bar.showMessage("Ошибка")
            self.log(f"Ошибка: {result['error']}")
        else:
            # После успешного создания doc.json генерируем Word
            self.generate_docx_from_file(result['file'])  # result['file'] = 'doc.json'

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())