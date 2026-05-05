from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import datetime
import json

class PostsListWindow(QDialog):
    saved = pyqtSignal()

    def __init__(self, posts, events, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор постов")
        self.setMinimumSize(800, 600)
        self.resize(1200, 800)
        self.setStyleSheet("background-color: #0f0f0f;")

        # Дедупликация постов (по url)
        unique_posts = {}
        for p in posts:
            url = p.get('url')
            if url and url not in unique_posts:
                unique_posts[url] = p
        posts = list(unique_posts.values())

        # Дедупликация событий (по дате+названию+описанию)
        unique_events = {}
        for e in events:
            key = (e.get('date', ''), e.get('name', ''), e.get('description', ''))
            if key not in unique_events:
                unique_events[key] = e
        events = list(unique_events.values())

        # Основной вертикальный макет
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Заголовок
        title = QLabel("Выберите посты, которые будут использоваться при создании документа")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: white; font-size: 14pt; font-weight: bold;")
        title.setWordWrap(True)
        main_layout.addWidget(title)

        # Легенда
        legend = QLabel("? Группы не указаны    = Возможно дубликат    ! Репост")
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        legend.setStyleSheet("""
            color: #ffaa00;
            font-size: 12pt;
            font-weight: bold;
            background-color: #2a2a2a;
            border: 1px solid #ffaa00;
            border-radius: 5px;
            padding: 8px;
        """)
        main_layout.addWidget(legend)

        # Прокручиваемая область
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none;")
        main_layout.addWidget(scroll, 1)

        # Виджет с карточками
        cards_widget = QWidget()
        self.cards_layout = QVBoxLayout(cards_widget)
        self.cards_layout.setSpacing(10)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(cards_widget)

        # Кнопка сохранения
        save_btn = QPushButton("Сохранить")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #00c853;
                color: black;
                border: none;
                border-radius: 5px;
                padding: 10px;
                font-size: 12pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00e676;
            }
        """)
        save_btn.clicked.connect(self.on_save)
        main_layout.addWidget(save_btn)

        # Подготовка данных
        self.all_items = []
        for p in posts:
            self.all_items.append({'type': 'post', 'data': p})
        for e in events:
            self.all_items.append({'type': 'event', 'data': e})

        # Сортировка по дате
        def get_date_obj(item):
            date_str = item['data'].get('date', '')
            if not date_str:
                return datetime.datetime.max
            try:
                return datetime.datetime.strptime(date_str, '%Y-%m-%d')
            except:
                return datetime.datetime.max
        self.all_items.sort(key=get_date_obj)

        # Подсчёт дат для индикатора "="
        date_counts = {}
        for item in self.all_items:
            date = item['data'].get('date')
            if date:
                date_counts[date] = date_counts.get(date, 0) + 1

        # Создание карточек
        self.card_items = []
        for item in self.all_items:
            card = self._create_card(item, date_counts)
            self.cards_layout.addWidget(card)
            self.card_items.append((card, item))

        # Добавляем растяжку в конец, чтобы карточки прижимались к верху
        self.cards_layout.addStretch()

    def _create_card(self, item, date_counts):
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setProperty("state", "none")
        # Ширина: 90% от ширины родительского виджета, но не более 1200
        card.setMinimumWidth(600)
        card.setMaximumWidth(1200)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        card.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border: 2px solid #333;
                border-radius: 8px;
                margin: 0px 20px;
            }
            QFrame[state="include"] { border-color: #00c853; }
            QFrame[state="exclude"] { border-color: #ff4444; }
        """)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)

        data = item['data']
        date = data.get('date', '')
        groups = data.get('groups', [])

        # Левая часть (индикаторы и кнопки)
        left = QWidget()
        left.setFixedWidth(120)
        left_layout = QVBoxLayout(left)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.setSpacing(5)

        # Индикаторы
        ind = QWidget()
        ind_layout = QHBoxLayout(ind)
        ind_layout.setContentsMargins(0, 0, 0, 0)
        ind_layout.setSpacing(2)
        ind_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if not groups:
            q = QLabel("?")
            q.setAlignment(Qt.AlignmentFlag.AlignCenter)
            q.setStyleSheet("font-size: 24pt; font-weight: bold; color: #00bcd4; background: transparent; border: none;")
            ind_layout.addWidget(q)

        if date_counts.get(date, 0) > 1:
            eq = QLabel("=")
            eq.setAlignment(Qt.AlignmentFlag.AlignCenter)
            eq.setStyleSheet("font-size: 24pt; font-weight: bold; color: #ff9800; background: transparent; border: none;")
            ind_layout.addWidget(eq)

        if item['type'] == 'post' and data.get('is_reposted', False):
            ex = QLabel("!")
            ex.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ex.setStyleSheet("font-size: 24pt; font-weight: bold; color: #ff4444; background: transparent; border: none;")
            ind_layout.addWidget(ex)

        left_layout.addWidget(ind)

        # Кнопки +/-
        btns = QWidget()
        btns_layout = QHBoxLayout(btns)
        btns_layout.setContentsMargins(0, 0, 0, 0)
        btns_layout.setSpacing(10)
        btns_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        plus = QPushButton("+")
        plus.setFixedSize(44, 44)
        plus.setStyleSheet("""
            QPushButton {
                background-color: #00c853;
                color: black;
                border: none;
                border-radius: 22px;
                font-size: 22pt;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover { background-color: #00e676; }
        """)
        plus.clicked.connect(lambda: self._set_card_state(card, 'include'))

        minus = QPushButton("-")
        minus.setFixedSize(44, 44)
        minus.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
                color: black;
                border: none;
                border-radius: 22px;
                font-size: 22pt;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover { background-color: #ff6666; }
        """)
        minus.clicked.connect(lambda: self._set_card_state(card, 'exclude'))

        btns_layout.addWidget(plus)
        btns_layout.addWidget(minus)
        left_layout.addWidget(btns)

        layout.addWidget(left)

        # Правая часть (информация)
        right = QWidget()
        right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(5)

        # Заголовок / ссылка
        if item['type'] == 'post':
            url = data.get('url', '#')
            title = QLabel(f'<a href="{url}" style="color: #ff9800; text-decoration: none;">Ссылка на пост</a>')
            title.setOpenExternalLinks(True)
            title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        else:
            name = data.get('name', 'Без названия')
            title = QLabel(name)
            title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #ff9800;")
        right_layout.addWidget(title)

        # Дата
        if date:
            try:
                d = datetime.datetime.strptime(date, '%Y-%m-%d')
                month_names = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                               'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
                date_str = f"{d.day} {month_names[d.month-1]}"
            except:
                date_str = date
            date_label = QLabel(date_str)
            date_label.setStyleSheet("color: #ff9800; font-size: 12pt; font-weight: bold;")
            right_layout.addWidget(date_label)

        # Источник (домен для постов, "А-Фишка" для событий)
        if item['type'] == 'post':
            source = data.get('source_domain', '')
            if source:
                source_label = QLabel(f"🌐 {source}")
                source_label.setStyleSheet("color: #aaaaaa; font-size: 10pt;")
                right_layout.addWidget(source_label)
        else:
            source_label = QLabel("📰 информация с А-Фишки")
            source_label.setStyleSheet("color: #aaaaaa; font-size: 10pt;")
            right_layout.addWidget(source_label)

        # Описание (QLabel с переносом)
        if item['type'] == 'post':
            body = data.get('body', '')
        else:
            body = data.get('description', '')

        if body:
            desc = QLabel(body)
            desc.setWordWrap(True)
            desc.setAlignment(Qt.AlignmentFlag.AlignLeft)
            desc.setStyleSheet("""
                QLabel {
                    background-color: transparent;
                    color: white;
                    font-size: 11pt;
                    margin-top: 5px;
                }
            """)
            desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            right_layout.addWidget(desc)

        # Группы (чипы)
        if groups:
            groups_widget = QWidget()
            groups_layout = QHBoxLayout(groups_widget)
            groups_layout.setContentsMargins(0, 0, 0, 0)
            groups_layout.setSpacing(5)
            for g in groups:
                chip = QLabel(g)
                chip.setStyleSheet("""
                    background-color: #333;
                    color: #00c853;
                    border: 1px solid #00c853;
                    border-radius: 12px;
                    padding: 4px 10px;
                    font-size: 10pt;
                """)
                groups_layout.addWidget(chip)
            groups_layout.addStretch()
            right_layout.addWidget(groups_widget)

        layout.addWidget(right, 1)
        return card

    def _set_card_state(self, card, state):
        card.setProperty("state", state)
        card.style().unpolish(card)
        card.style().polish(card)

    def on_save(self):
        selected = []
        for card, item in self.card_items:
            if card.property("state") == "include":
                data = item['data']
                if item['type'] == 'post':
                    selected.append({
                        'source_type': 'post',
                        'date': data.get('date', ''),
                        'title': '',
                        'description': data.get('body', ''),
                        'location': '',
                        'url': data.get('url', 'Соцсети колледжа'),
                        'groups': data.get('groups', []),
                        'is_reposted': data.get('is_reposted', False),
                        'source_domain': data.get('source_domain', '')
                    })
                else:
                    selected.append({
                        'source_type': 'event',
                        'date': data.get('date', ''),
                        'title': data.get('name', ''),
                        'description': data.get('description', ''),
                        'location': data.get('location', ''),
                        'url': data.get('url', 'Соцсети колледжа'),
                        'groups': data.get('groups', []),
                        'source_domain': data.get('source_domain', 'А-Фишка')
                    })
        with open('selected_items.json', 'w', encoding='utf-8') as f:
            json.dump(selected, f, ensure_ascii=False, indent=2)

        self.saved.emit()
        QMessageBox.information(self, "Сохранение", f"Выбрано записей: {len(selected)}. Данные сохранены.")