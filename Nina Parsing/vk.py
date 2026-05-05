import sys
import os
import shutil
import time
import requests
import json
import re
from datetime import datetime, timedelta
import pytesseract
from PIL import Image
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QComboBox, QPushButton, QFrame, QListWidget,
                             QListWidgetItem, QDialog, QDialogButtonBox, QSpinBox, QDateEdit,
                             QMessageBox, QStatusBar, QLayout, QProgressBar)
from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal, QObject, QSettings
from PyQt6.QtGui import QFont

# ------------------ Настройка Tesseract ------------------
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

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
    'ПД-23-1', 'ПД-23-2', 'ТМ-23', 'ТОР-22', 'И-22', 'ИСП-22', 'ТМП-22', 'ПД-22'
]

# ------------------ Вспомогательные функции (без изменений) ------------------
def normalize_text(text):
    return re.sub(r'[‒–—―‑]', '-', text)

def find_groups(text, group_list=None):
    if group_list is None:
        group_list = GROUPS
    text = normalize_text(text)
    found = []
    for g in group_list:
        if re.search(r'(^|\s)' + re.escape(g) + r'($|\s|[.,!?;])', text, re.IGNORECASE):
            found.append(g)
    return found

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

def ocr_image_tesseract(image_path):
    try:
        img = Image.open(image_path).convert('RGB')
        text = pytesseract.image_to_string(img, lang='rus').strip()
        return text
    except Exception as e:
        print(f"Ошибка OCR для {image_path}: {e}")
        return ""

def parse_event_date(text, post_date):
    MONTHS = {
        'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
        'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
        'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
    }
    t = text.lower()
    if re.search(r'сегодня|в этот день', t):
        return post_date.strftime('%Y-%m-%d')
    m = re.search(r'(\d{1,2})\s+(' + '|'.join(MONTHS.keys()) + ')', t)
    if m:
        day = int(m.group(1))
        month_name = m.group(2)
        month = MONTHS[month_name]
        year = post_date.year
        if month < post_date.month:
            year += 1
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            return None
    return None

def take_posts_date_range(domain, token, start_date, end_date, max_posts=150):
    offset = 0
    collected = []
    per_request = 100
    start_ts = int(start_date.timestamp())
    end_ts = int(end_date.timestamp()) + 86399

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
                if post_ts < start_ts:
                    return collected
                if start_ts <= post_ts <= end_ts:
                    collected.append(post)
                    if len(collected) >= max_posts:
                        return collected

            offset += per_request
            time.sleep(0.3)
        except Exception as e:
            print(f"Ошибка при запросе к VK: {e}")
            break
    return collected

def process_post(post, img_dir, selected_group=None):
    txt = post.get('text', '').strip()
    post_date = datetime.fromtimestamp(post['date'])
    event_date = parse_event_date(txt, post_date) if txt else None
    final_date = event_date if event_date else post_date.strftime('%Y-%m-%d')

    attachments = post.get('attachments', [])
    photos = [att for att in attachments if att['type'] == 'photo']
    has_single_photo = len(photos) == 1

    # Определяем, нужно ли обрабатывать фото
    process_photo = False
    photo_path = None
    groups_from_photo = []
    ocr_text_photo = ""

    if has_single_photo:
        if not txt:
            # Только фото
            process_photo = True
        elif len(txt) <= 40:
            # Короткий текст + одно фото
            process_photo = True
        # else: длинный текст + фото -> фото игнорируем

    if process_photo:
        photo = photos[0]['photo']
        photo_url = best_photo_url(photo)
        if photo_url:
            filename = f"{final_date}_{post['owner_id']}_{post['id']}.jpg"
            path = os.path.join(img_dir, filename)
            if download_photo(photo_url, path):
                print(f"OCR: {path}")
                ocr_text_photo = ocr_image_tesseract(path)
                groups_from_photo = find_groups(ocr_text_photo) if ocr_text_photo else []
                if groups_from_photo:
                    photo_path = path
                else:
                    os.remove(path)
            # если фото не скачалось – ничего не делаем

    # Группы из текста
    groups_from_text = find_groups(txt) if txt else []

    # Есть ли текст
    has_text = bool(txt)

    if has_text:
        # Текстовый пост (возможно, с фото)
        if selected_group:
            # Если группа выбрана
            if not groups_from_text:
                # В тексте нет групп – сохраняем
                pass
            elif selected_group in groups_from_text:
                # Есть выбранная группа – сохраняем
                pass
            else:
                # В тексте есть другие группы, но нет выбранной – не сохраняем
                return None
        # Группа не выбрана – сохраняем всегда

        all_groups = groups_from_text + groups_from_photo
        return {
            'body': txt,
            'url': f"https://vk.com/wall{post['owner_id']}_{post['id']}",
            'date': final_date,
            'groups': list(set(all_groups)),
            'photo_path': photo_path
        }
    else:
        # Нет текста – полагаемся только на фото
        if process_photo and groups_from_photo:
            if selected_group and selected_group not in groups_from_photo:
                return None
            return {
                'body': '',
                'url': f"https://vk.com/wall{post['owner_id']}_{post['id']}",
                'date': final_date,
                'groups': groups_from_photo,
                'photo_path': photo_path
            }
        else:
            return None
# ------------------ Функция для извлечения домена из ссылки ------------------
def extract_domain_from_url(text):
    """
    Извлекает домен (short name) из ссылки на группу ВК.
    Примеры:
        https://vk.com/zhgmk_professionalitet -> zhgmk_professionalitet
        https://vk.com/club123456 -> club123456
        vk.com/durov -> durov
        durov (если уже домен) -> durov
    """
    text = text.strip()
    # Регулярное выражение для поиска домена после vk.com/
    match = re.search(r'(?:https?://)?(?:www\.)?vk\.com/([a-zA-Z0-9_.-]+)', text)
    if match:
        return match.group(1)
    # Если не похоже на ссылку, возвращаем как есть (возможно, уже домен)
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
        # Извлекаем домен из введённого текста (ссылки или просто домена)
        raw = self.line_edit.text().strip()
        return extract_domain_from_url(raw)

# ------------------ Рабочий поток для сбора постов ------------------
class Worker(QObject):
    finished = pyqtSignal(dict)  # сигнал с результатом или ошибкой
    progress = pyqtSignal(str)    # текстовый статус
    progress_value = pyqtSignal(int, int)  # текущее значение и максимум

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
        try:
            start = datetime.strptime(self.start_date, '%Y-%m-%d')
            end = datetime.strptime(self.end_date, '%Y-%m-%d')
        except ValueError:
            self.finished.emit({'error': 'Неверный формат даты. Используйте ГГГГ-ММ-ДД.'})
            return

        if (end - start) > timedelta(days=60):
            self.finished.emit({'error': 'Период не должен превышать 2 месяца.'})
            return

        all_results = []
        domains_to_scan = [self.domain] + self.additional_domains

        total_domains = len(domains_to_scan)
        for idx_dom, dom in enumerate(domains_to_scan):
            if not dom:
                continue
            self.progress.emit(f"Сканирование домена: {dom}")
            img_dir = f'images_{dom}'
            if os.path.exists(img_dir):
                shutil.rmtree(img_dir)
            os.makedirs(img_dir)

            posts = take_posts_date_range(dom, self.token, start, end, max_posts=self.max_posts)
            self.progress.emit(f"Домен {dom}: собрано {len(posts)} постов")

            # Обрабатываем посты
            for i, post in enumerate(posts):
                r = process_post(post, img_dir, self.selected_group)
                if r:
                    r['source_domain'] = dom
                    all_results.append(r)
                # Обновляем прогресс
                progress_value = idx_dom * len(posts) + i + 1
                progress_max = total_domains * self.max_posts
                self.progress_value.emit(progress_value, progress_max)

        output_file = 'posts.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

        self.finished.emit({'success': True, 'count': len(all_results), 'file': output_file})

# ------------------ Главное окно ------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VK Post Scanner")
        self.setGeometry(100, 100, 1000, 700)
        self.setStyleSheet(self.get_stylesheet())

        self.additional_domains = []
        self.settings = QSettings("config.ini", QSettings.Format.IniFormat)  # используем QSettings для сохранения

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        header = QLabel("Тут когда-нибудь будет название")
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

        # Поля ввода
        self.domain_edit = self.create_line_edit("zhgmk_professionalitet")
        left_layout.addWidget(self.create_labeled_widget("Ссылка/домен:", self.domain_edit))

        self.token_edit = self.create_line_edit("", password=True)
        left_layout.addWidget(self.create_labeled_widget("Token:", self.token_edit))

        self.group_combo = QComboBox()
        self.group_combo.addItem("")
        self.group_combo.addItems(GROUPS)
        self.group_combo.setEditable(True)
        self.group_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.group_combo.setStyleSheet("""
            QComboBox {
                background-color: #2f2f2f;
                color: white;
                border: 2px solid #00c853;
                padding: 5px;
                font-size: 12pt;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2f2f2f;
                color: white;
                selection-background-color: #00c853;
            }
        """)
        left_layout.addWidget(self.create_labeled_widget("Группа:", self.group_combo))

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

        left_layout.addWidget(self.create_labeled_widget("Даты:", date_layout))

        # Макс. постов
        self.max_posts_spin = QSpinBox()
        self.max_posts_spin.setRange(1, 500)
        self.max_posts_spin.setValue(150)
        self.max_posts_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2f2f2f;
                color: white;
                border: 2px solid #00c853;
                padding: 5px;
                font-size: 12pt;
            }
        """)
        left_layout.addWidget(self.create_labeled_widget("Макс. постов:", self.max_posts_spin))

        # Кнопки
        buttons_layout = QHBoxLayout()
        self.scan_button = self.create_button("Сканировать посты", self.start_scan)
        buttons_layout.addWidget(self.scan_button)

        self.doc_button = self.create_button("Создать документ", self.create_document)
        buttons_layout.addWidget(self.doc_button)

        left_layout.addLayout(buttons_layout)
        left_layout.addStretch()

        columns_layout.addWidget(left_column, 45)

        # Правая колонка
        right_column = QFrame()
        right_column.setFrameShape(QFrame.Shape.Box)
        right_column.setStyleSheet("""
            QFrame {
                border: 2px solid white;
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
                font-size: 12pt;
            }
            QListWidget::item {
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #00c853;
            }
        """)
        right_layout.addWidget(self.domains_list)

        columns_layout.addWidget(right_column, 45)

        # Прогресс-бар и статус
        bottom_layout = QHBoxLayout()
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
                width: 10px;
            }
        """)
        bottom_layout.addWidget(self.progress_bar)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet("color: #00c853; background-color: #0f0f0f;")

        main_layout.addLayout(bottom_layout)

        # Поток
        self.thread = None
        self.worker = None

        self.load_config()

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
        """

    def get_date_edit_style(self):
        return """
            QDateEdit {
                background-color: #2f2f2f;
                color: white;
                border: 2px solid #00c853;
                padding: 5px;
                font-size: 12pt;
            }
            QDateEdit::drop-down {
                border: none;
            }
            QDateEdit::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                width: 0px;
                height: 0px;
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
        label.setFixedWidth(120)
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

    def add_domain(self):
        dialog = AddDomainDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            domain = dialog.get_domain()
            if domain and domain not in self.additional_domains:
                self.additional_domains.append(domain)
                self.domains_list.addItem(domain)
                self.save_config()  # сразу сохраняем
            elif domain in self.additional_domains:
                QMessageBox.warning(self, "Предупреждение", "Этот домен уже добавлен.")

    def save_config(self):
        """Сохраняет текущие настройки в config.ini через QSettings"""
        self.settings.setValue("domain", self.domain_edit.text())
        self.settings.setValue("token", self.token_edit.text())
        self.settings.setValue("group", self.group_combo.currentText())
        self.settings.setValue("start_date", self.start_date_edit.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("end_date", self.end_date_edit.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("max_posts", self.max_posts_spin.value())
        # Сохраняем дополнительные домены как список строк
        self.settings.setValue("additional_domains", json.dumps(self.additional_domains))

    def load_config(self):
        """Загружает настройки из config.ini и заполняет поля"""
        domain = self.settings.value("domain", "zhgmk_professionalitet")
        self.domain_edit.setText(domain)
        token = self.settings.value("token", "")
        self.token_edit.setText(token)
        group = self.settings.value("group", "")
        self.group_combo.setCurrentText(group)
        start_date_str = self.settings.value("start_date", QDate.currentDate().toString(Qt.DateFormat.ISODate))
        self.start_date_edit.setDate(QDate.fromString(start_date_str, Qt.DateFormat.ISODate))
        end_date_str = self.settings.value("end_date", QDate.currentDate().toString(Qt.DateFormat.ISODate))
        self.end_date_edit.setDate(QDate.fromString(end_date_str, Qt.DateFormat.ISODate))
        max_posts = int(self.settings.value("max_posts", 150))
        self.max_posts_spin.setValue(max_posts)
        additional_domains_json = self.settings.value("additional_domains", "[]")
        try:
            self.additional_domains = json.loads(additional_domains_json)
        except:
            self.additional_domains = []
        # Заполняем список
        self.domains_list.clear()
        for dom in self.additional_domains:
            self.domains_list.addItem(dom)

    def start_scan(self):
        # Сохраняем конфигурацию
        self.save_config()

        self.scan_button.setEnabled(False)
        self.status_bar.showMessage("Сканирование...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

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
        self.worker.progress_value.connect(self.progress_bar.setValue)
        # При максимуме прогресса можно установить range
        self.worker.progress_value.connect(lambda val, max_val: self.progress_bar.setMaximum(max_val))

        self.thread.start()

    def on_scan_finished(self, result):
        self.scan_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        if 'error' in result:
            QMessageBox.critical(self, "Ошибка", result['error'])
            self.status_bar.showMessage("Ошибка")
        else:
            QMessageBox.information(self, "Успех",
                                   f"Собрано записей: {result['count']}\nРезультат сохранён в {result['file']}")
            self.status_bar.showMessage("Готово")

    def create_document(self):
        QMessageBox.information(self, "Информация", "Функция 'Создать документ' ещё не реализована.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())