import asyncio
import re
import json
import os
from dataclasses import dataclass
from typing import List, Optional, Set

import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums.parse_mode import ParseMode

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))  # Преобразуем в число

if not BOT_TOKEN or ADMIN_CHAT_ID == 0:
    raise ValueError("BOT_TOKEN и ADMIN_CHAT_ID должны быть установлены в переменных окружения!")
    
# Куки и заголовки для авторизации на FunPay
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Sec-Ch-Ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
    'Connection': 'keep-alive'
}

COOKIES = {
    'golden_key': '2t5853ola0uv1fw7bazhvv6kru4xbxzl',
    '_ym_uid': '1769628684270636036',
    '_ym_d': '1769628684',
    '_ga': 'GA1.1.1252175048.1769628684',
    'cookie_prefs': '1',
    '_gcl_au': '1.1.1254374906.1769628684.1956698634.1769967097.1769967097',
    'fav_games': '334-159-120-123-351-141',
    '_ym_isad': '2',
    '_ga_STVL2Q8BNQ': 'GS2.1.s1770731468$o39$g1$t1770731469$j59$l0$h1604990623'
}

# Параметры фильтрации
MIN_CUPS = 700
MIN_PRICE = 10.0
MAX_PRICE = 20.0

# URL страницы лотов
LOTS_URL = "https://funpay.com/lots/149/"

# Файл для хранения ID отправленных лотов
SENT_IDS_FILE = "sent_ids.json"
# ===================================================

@dataclass
class FunPayLot:
    """Структура данных лота"""
    offer_id: int                # уникальный идентификатор лота
    title: str
    link: str
    price: float
    arena: int
    level: int
    cups: int
    cards: int
    namechange: str
    auto_delivery: bool = False
    promo: bool = False

    def to_message(self) -> str:
        """Формирует текст сообщения для отправки в Telegram"""
        lines = [
            f"🏷 {self.title}\n",
            f"🔗 {self.link}\n",
            f"💰 {self.price:.2f} ₽\n",
            f"🏟 Арена: {self.arena}",
            f"📊 Уровень: {self.level}",
            f"🏆 Кубки: {self.cups}",
            f"🃏 Карт: {self.cards}",
            f"🔄 Смена ника: {self.namechange}",
            f"⚡️ Автовыдача: {'Да' if self.auto_delivery else 'Нет'}",
            f"🔥 Промо: {'Да' if self.promo else 'Нет'}"
        ]
        return "\n".join(lines)


class FunPayParser:
    """Парсер лотов FunPay"""
    def __init__(self, headers: dict, cookies: dict):
        self.session = requests.Session()
        self.session.headers.update(headers)
        self.session.cookies.update(cookies)

    def fetch_page(self, url: str) -> Optional[str]:
        """Загружает HTML страницы"""
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"Ошибка загрузки страницы: {e}")
            return None

    def parse_lot(self, lot_tag) -> Optional[FunPayLot]:
        """Извлекает данные из одного тега <a> лота"""
        try:
            # Основные атрибуты из тега <a>
            link = lot_tag.get('href', '')
            if not link.startswith('http'):
                link = 'https://funpay.com' + link

            # Извлекаем offer_id из ссылки
            id_match = re.search(r'id=(\d+)', link)
            if not id_match:
                return None
            offer_id = int(id_match.group(1))

            # Данные из data-атрибутов
            arena = int(lot_tag.get('data-f-arena', 0))
            level = int(lot_tag.get('data-f-level', 0))
            cups = int(lot_tag.get('data-f-cup', 0))
            cards = int(lot_tag.get('data-f-card', 0))
            namechange = lot_tag.get('data-f-namechange', 'нет')
            auto = lot_tag.get('data-auto') == '1'
            promo = 'offer-promo' in lot_tag.get('class', '')

            # Цена
            price_div = lot_tag.find('div', class_='tc-price')
            if not price_div:
                return None
            price_text = price_div.get_text(strip=True)
            price_match = re.search(r'([\d.,]+)', price_text.replace(' ', ''))
            if not price_match:
                return None
            price_str = price_match.group(1).replace(',', '.')
            try:
                price = float(price_str)
            except ValueError:
                return None

            # Название (tc-desc-text)
            desc_div = lot_tag.find('div', class_='tc-desc')
            if not desc_div:
                return None
            title_div = desc_div.find('div', class_='tc-desc-text')
            title = title_div.get_text(strip=True) if title_div else ''

            return FunPayLot(
                offer_id=offer_id,
                title=title,
                link=link,
                price=price,
                arena=arena,
                level=level,
                cups=cups,
                cards=cards,
                namechange=namechange,
                auto_delivery=auto,
                promo=promo
            )
        except Exception as e:
            print(f"Ошибка парсинга лота: {e}")
            return None

    def get_all_lots(self, html: str) -> List[FunPayLot]:
        """Парсит всю таблицу лотов"""
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('div', class_='tc table-hover table-clickable tc-short showcase-table tc-lazyload tc-sortable showcase-has-promo')
        if not table:
            print("Таблица лотов не найдена")
            return []
        lots = []
        for item in table.find_all('a', class_='tc-item'):
            lot = self.parse_lot(item)
            if lot:
                lots.append(lot)
        return lots

    def filter_lots(self, lots: List[FunPayLot]) -> List[FunPayLot]:
        """Фильтрует лоты по условиям: кубки >= 700, цена 10-35 руб"""
        filtered = []
        for lot in lots:
            if lot.cups >= MIN_CUPS and MIN_PRICE <= lot.price <= MAX_PRICE:
                filtered.append(lot)
        return filtered


class FunPayMonitor:
    """Мониторинг лотов и отправка в Telegram"""
    def __init__(self, bot: Bot, parser: FunPayParser):
        self.bot = bot
        self.parser = parser
        self.is_running = False
        self.sent_ids: Set[int] = set()
        self.load_sent_ids()

    def load_sent_ids(self):
        """Загружает ID уже отправленных лотов из файла"""
        if os.path.exists(SENT_IDS_FILE):
            try:
                with open(SENT_IDS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.sent_ids = set(data)
                print(f"Загружено {len(self.sent_ids)} отправленных ID")
            except Exception as e:
                print(f"Ошибка загрузки sent_ids: {e}")
                self.sent_ids = set()
        else:
            self.sent_ids = set()

    def save_sent_ids(self):
        """Сохраняет ID отправленных лотов в файл"""
        try:
            with open(SENT_IDS_FILE, 'w', encoding='utf-8') as f:
                json.dump(list(self.sent_ids), f, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения sent_ids: {e}")

    async def start_monitoring(self, chat_id: int):
        """Запускает бесконечный цикл парсинга"""
        self.is_running = True
        await self.bot.send_message(chat_id, "✅ Мониторинг лотов FunPay запущен")
        while self.is_running:
            try:
                # Загружаем страницу
                html = self.parser.fetch_page(LOTS_URL)
                if not html:
                    await asyncio.sleep(30)
                    continue

                # Парсим все лоты
                all_lots = self.parser.get_all_lots(html)
                # Фильтруем
                good_lots = self.parser.filter_lots(all_lots)

                # Отправляем каждый новый подходящий лот
                for lot in good_lots:
                    if lot.offer_id not in self.sent_ids:
                        await self.bot.send_message(
                            chat_id,
                            lot.to_message(),
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=False
                        )
                        self.sent_ids.add(lot.offer_id)
                        self.save_sent_ids()  # сохраняем после каждого добавления
                        await asyncio.sleep(1)  # пауза между сообщениями

            except Exception as e:
                await self.bot.send_message(chat_id, f"⚠️ Ошибка в цикле парсинга:\n{e}")
                print(f"Ошибка в цикле: {e}")

            await asyncio.sleep(30)  # пауза 30 секунд

    def stop_monitoring(self):
        self.is_running = False
        self.save_sent_ids()  # сохраняем при остановке


# ==================== ТЕЛЕГРАМ БОТ ====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
monitor = None


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start – запускает мониторинг"""
    global monitor
    if message.chat.id != ADMIN_CHAT_ID:
        await message.answer("❌ У вас нет прав на использование этого бота.")
        return

    if monitor and monitor.is_running:
        await message.answer("⚠️ Мониторинг уже запущен.")
        return

    parser = FunPayParser(HEADERS, COOKIES)
    monitor = FunPayMonitor(bot, parser)
    # Запускаем мониторинг в фоновой задаче
    asyncio.create_task(monitor.start_monitoring(message.chat.id))
    await message.answer("🔄 Мониторинг запущен!")


@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    """Команда /stop – останавливает мониторинг"""
    global monitor
    if message.chat.id != ADMIN_CHAT_ID:
        await message.answer("❌ Нет прав.")
        return

    if monitor and monitor.is_running:
        monitor.stop_monitoring()
        await message.answer("⏹ Мониторинг остановлен.")
    else:
        await message.answer("ℹ️ Мониторинг не запущен.")


@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Команда /status – показывает статус"""
    if message.chat.id != ADMIN_CHAT_ID:
        return
    if monitor and monitor.is_running:
        await message.answer("✅ Мониторинг активен.")
    else:
        await message.answer("⏸ Мониторинг остановлен.")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
