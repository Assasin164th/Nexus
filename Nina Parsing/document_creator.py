# document_creator.py
import json
import os
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

def log_gigachat_response(text, context=""):
    """Сохраняет ответ нейросети в файл с меткой времени и контекстом."""
    try:
        with open("gigachat_responses.log", "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {context}\n{text}\n{'-'*50}\n")
    except Exception:
        pass  # не ломаем основную логику, если запись не удалась

class DocumentCreator(QObject):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int, int)

    def __init__(self, input_file, credentials, scope, model="GigaChat-2"):
        super().__init__()
        self.input_file = input_file
        self.credentials = credentials
        self.scope = scope
        self.model = model

    def run(self):
        try:
            # 1. Загружаем выбранные посты
            if not os.path.exists(self.input_file):
                self.finished.emit({'error': f'Файл {self.input_file} не найден. Сначала выберите посты.'})
                return

            with open(self.input_file, 'r', encoding='utf-8') as f:
                items = json.load(f)

            if not items:
                self.finished.emit({'error': 'Нет выбранных постов.'})
                return

            self.progress.emit(f"Загружено записей: {len(items)}")
            self.progress_value.emit(0, len(items))

            # 2. Формируем промпт для модели
            prompt = self._build_prompt(items)
            self.progress.emit("Отправка запроса в GigaChat...")

            # 3. Инициализация клиента
            client = GigaChat(
                credentials=self.credentials,
                scope=self.scope,
                verify_ssl_certs=False,
                timeout=600,
                model=self.model
            )

            # 4. Отправляем запрос
            response = client.chat(
                Chat(
                    messages=[
                        Messages(
                            role=MessagesRole.USER,
                            content=prompt
                        )
                    ],
                    temperature=0.1,
                )
            )

            content = response.choices[0].message.content.strip()
            log_gigachat_response(content, context="Document creation")
            client.close()

            # 5. Парсим ответ
            parsed = self._parse_response(content, len(items))
            if 'error' in parsed:
                self.finished.emit(parsed)
                return

            # 6. Сохраняем результат
            output_file = 'doc.json'
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(parsed['data'], f, ensure_ascii=False, indent=2)

            self.progress.emit(f"Документ сохранён в {output_file}")
            self.finished.emit({'success': True, 'file': output_file, 'count': len(parsed['data'])})

        except Exception as e:
            self.finished.emit({'error': str(e)})

    def _build_prompt(self, items):
        """Формирует текст запроса для GigaChat."""
        prompt = (
            "Ты получаешь список записей о мероприятиях. Для КАЖДОЙ записи сгенерируй ОДНУ строку в формате:\n"
            "Дата | Название мероприятия | Уровень | Место проведения | Форма проведения | Формат участия | Краткое описание, результат | Ссылка | Направление\n\n"
            "Возможные значения для полей:\n"
            "- Уровень: Город, Колледж, Область (выбери наиболее подходящий или оставь пустым)\n"
            "- Форма проведения: Классный час(КлЧ), Волонтерская акция(ВолА), Родительское собрание(РодС), Презентация (През), Мастер-класс(МК), Конф, Форум, Региональные и всероссийские акции (Рег), проекты, Иные формы(ИН)\n"
            "- Формат участия: Очный (Оч), Дистанционный(Дист), Смешанный(Смеш)\n"
            "- Направление: Гражданско-патриотическое воспитание(ГПВ), добровольческая деятельность(ДД), духовно-нравственное воспитание(ДНВ), естественно-научная направленность(ЕНН), творческая направленность(ТН), безопасность жизнедеятельности и здоровый образ жизни(БЖД), экологическая направленность(ЭН), развитие лидерских качеств(РЛК), воспитание ценности научного познания(ЦНП)\n\n"
            "Правила:\n"
            "- Ссылка: используй ссылку из исходной записи, если её нет — укажи 'Соцсети колледжа'.\n"
            "- Если информации недостаточно, постарайся определить подходящее значение из предложенных вариантов. Если невозможно — оставь поле пустым. Используй только сокращения,которые я указал выше и не придумывай своих вариантов ответа, если я предложил какие-то\n"
            "- **Не добавляй никаких пояснений, разделителей или пустых строк. Только строки с данными, каждая на отдельной строке.**\n"
            "- Количество строк должно точно соответствовать количеству записей.\n\n"
            "Пример правильного ответа (для двух записей):\n"
            "2026-01-28 | Встреча с кадровым центром | Колледж | ЖГМК | МК | Оч | Мастер-класс по резюме, в ходе которого были продемонстрированы примеры идеальных резюме и правила их составления | https://vk.com/... | РЛК\n"
            "2026-01-26 | Викторина | Колледж | Ауд. 113 Колледжа | ИН | Оч | В ходе викторины студенты проверили уровень своих знаний навыков, обрели соревновательный дух и подняли своё настроение | Соцсети колледжа | ЦНП\n\n"
            "Исходные записи:\n"
        )
        for idx, item in enumerate(items, 1):
            if item['source_type'] == 'post':
                prompt += f"\nЗапись {idx} (пост): Дата: {item.get('date', '')}, Текст: {item.get('description', '')}, Ссылка: {item.get('url', '')}, Группы: {', '.join(item.get('groups', []))}"
            else:
                prompt += f"\nЗапись {idx} (событие): Дата: {item.get('date', '')}, Название: {item.get('title', '')}, Описание: {item.get('description', '')}, Место: {item.get('location', '')}, Ссылка: {item.get('url', 'Соцсети колледжа')}, Группы: {', '.join(item.get('groups', []))}"
        return prompt

    def _parse_response(self, content, expected_count):
        """Парсит ответ модели и возвращает список словарей."""
        lines = content.strip().split('\n')
        result = []
        errors = []
        for i, line in enumerate(lines):
            line = line.strip()
            # Пропускаем пустые строки и строки-разделители
            if not line or line.startswith('---') or line.startswith('==='):
                continue
            parts = line.split('|')
            if len(parts) != 9:
                errors.append(f"Строка {i+1}: ожидалось 9 полей, получено {len(parts)}: {line[:50]}...")
                continue
            parts = [p.strip() for p in parts]
            result.append({
                'date': parts[0],
                'name': parts[1],
                'level': parts[2],
                'location': parts[3],
                'form_type': parts[4],
                'participation_format': parts[5],
                'description_result': parts[6],
                'link': parts[7],
                'direction': parts[8]
            })
        if len(result) != expected_count:
            errors.append(f"Ожидалось {expected_count} записей, получено {len(result)}")
        if errors:
            return {'error': 'Ошибки при парсинге ответа:\n' + '\n'.join(errors)}
        return {'data': result}