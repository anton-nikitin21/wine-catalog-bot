#python tg_bot.py
import os
import re
import csv
import time
import logging
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt

from scipy.stats import chi2_contingency, ttest_ind, f_oneway, pearsonr

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# ЛОГИРОВАНИЕ
# =========================
import logging

# формат
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"

# логгер
logger = logging.getLogger("wine_logger")
logger.setLevel(logging.DEBUG)

# файл
file_handler = logging.FileHandler("py_log.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

# консоль
from colorlog import ColoredFormatter

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

color_formatter = ColoredFormatter(
    "%(log_color)s%(asctime)s | %(levelname)s | %(message)s",
    log_colors={
        "DEBUG": "cyan",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold_red",
    }
)

console_handler.setFormatter(color_formatter)
logger.addHandler(console_handler)

# добавляем
logger.addHandler(file_handler)
logger.addHandler(console_handler)


# =========================
# НАСТРОЙКИ
# =========================
BASE_URL = "https://vinnayagramota.ru"
CATALOG_URL = "https://vinnayagramota.ru/vino"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
}

PLOTS_DIR = "plots"
os.makedirs(PLOTS_DIR, exist_ok=True)

# =========================
# ПАРСИНГ
# =========================
def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def get_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_first_number(text: str) -> str:
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return match.group(1).replace(",", ".") if match else ""


def extract_price(text: str) -> str:
    match = re.search(r"(\d[\d\s,]*\.\d{2})\s*₽", text.replace("\xa0", " "))
    return match.group(1).replace(" ", "").replace(",", "") if match else ""


def extract_field(block_text: str, field_name: str, stop_fields: list[str]) -> str:
    stop_pattern = "|".join(re.escape(x) for x in stop_fields)
    pattern = rf"{re.escape(field_name)}:\s*(.*?)(?=\s+(?:{stop_pattern}):|$)"
    match = re.search(pattern, block_text, flags=re.IGNORECASE | re.DOTALL)
    return clean_text(match.group(1)) if match else ""


def extract_year(name: str, specs_block: str, page_text: str) -> str:
    patterns = [
        r"Урожай[:\s]+((?:19|20)\d{2})",
        r"\b((?:19|20)\d{2})\b",
    ]

    if specs_block:
        m = re.search(patterns[0], specs_block, flags=re.IGNORECASE)
        if m:
            return m.group(1)

    if specs_block:
        m = re.search(patterns[1], specs_block)
        if m:
            return m.group(1)

    if name:
        m = re.search(patterns[1], name)
        if m:
            return m.group(1)

    if page_text:
        m = re.search(patterns[0], page_text, flags=re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(patterns[1], page_text)
        if m:
            return m.group(1)

    return ""


def get_product_links(limit=20) -> list[str]:
    soup = get_soup(CATALOG_URL)
    links = []
    seen = set()

    bad_parts = {
        "beloe-vino", "krasnoe-vino", "rozovoe-vino",
        "suhoe-vino", "polusuhoe-vino", "polusladkoe-vino", "sladkoe-vino",
        "igristoe-vino", "frantsiya", "italiya", "ispaniya", "argentina",
        "germaniya", "portugaliya", "chili", "rossiya", "novaya-zelandiya",
        "avstriya", "yuar", "armeniya", "gruziya"
    }

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full_url = urljoin(BASE_URL, href).split("#")[0].split("?")[0]

        if not full_url.startswith(BASE_URL + "/vino/"):
            continue
        if full_url.rstrip("/") == CATALOG_URL.rstrip("/"):
            continue

        slug = full_url.rstrip("/").split("/")[-1].lower()
        if slug in bad_parts:
            continue
        if slug.count("-") < 3:
            continue

        if full_url not in seen:
            seen.add(full_url)
            links.append(full_url)

    return links[:limit]


def extract_specs_block(page_text: str) -> str:
    start_candidates = []
    for marker in ["Производитель:", "Цвет:"]:
        idx = page_text.find(marker)
        if idx != -1:
            start_candidates.append(idx)

    start = min(start_candidates) if start_candidates else 0

    end_markers = [
        "Рейтинги и награды", "В магазине", "В корзину",
        "Описание", "Гастрономия", "Отзывы", "Похожие товары"
    ]
    end_positions = [page_text.find(m, start) for m in end_markers if page_text.find(m, start) != -1]
    end = min(end_positions) if end_positions else len(page_text)

    return clean_text(page_text[start:end])


def parse_product_page(url: str) -> dict:
    soup = get_soup(url)
    page_text = clean_text(soup.get_text(" ", strip=True))

    h1 = soup.find("h1")
    name = clean_text(h1.get_text(" ", strip=True)) if h1 else ""

    specs_block = extract_specs_block(page_text)
    year = extract_year(name, specs_block, page_text)

    color = extract_field(specs_block, "Цвет", ["Сахар", "Виноград", "Регион", "Крепость", "Страна", "Урожай", "Объем"])
    sugar = extract_field(specs_block, "Сахар", ["Виноград", "Регион", "Крепость", "Страна", "Урожай", "Объем"])
    grape = extract_field(specs_block, "Виноград", ["Регион", "Крепость", "Страна", "Урожай", "Объем"])
    country = extract_field(specs_block, "Страна", ["Урожай", "Объем", "Рейтинги и награды", "В магазине", "В корзину"])
    volume = extract_field(specs_block, "Объем", ["Рейтинги и награды", "В магазине", "В корзину"])
    volume = extract_first_number(volume) if volume else ""

    title_pos = page_text.find(name) if name else 0
    search_zone = page_text[title_pos:title_pos + 1500] if title_pos != -1 else page_text[:1500]
    price = extract_price(search_zone)

    return {
        "name": name,
        "year": year,
        "color": color,
        "sugar": sugar,
        "grape": grape,
        "country": country,
        "volume": volume,
        "price": price,
    }


def save_to_csv(rows: list[dict], filename="wine.csv") -> None:
    fieldnames = ["name", "year", "color", "sugar", "grape", "country", "volume", "price"]
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_all_wines(limit=50):
    logger.info("Начало парсинга вин")
    links = get_product_links(limit=limit)
    rows = []
    seen = set()

    for i, link in enumerate(links, start=1):
        logger.debug(f"Парсинг ссылки {i}/{len(links)}: {link}")
        try:
            row = parse_product_page(link)
            key = (row["name"], row["price"])
            if row["name"] and key not in seen:
                seen.add(key)
                rows.append(row)
            time.sleep(0.3)
        except Exception as e:
            logger.error(f"Ошибка при обработке {link}: {e}")

    save_to_csv(rows, "wine.csv")
    logger.info(f"Парсинг завершён. Сохранено строк: {len(rows)}")
    return rows

# =========================
# ЗАДАНИЕ 2
# =========================
def load_and_prepare_data(filename="wine.csv") -> pd.DataFrame:
    df = pd.read_csv(filename, encoding="utf-8-sig")

    for col in ["name", "color", "sugar", "grape", "country"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    for col in ["price", "year", "volume"]:
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                .str.replace(",", ".", regex=False)
                .str.extract(r"(\d+(?:\.\d+)?)")[0]
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def task_2_analysis(df: pd.DataFrame):
    france_df = df[df["country"].str.lower().str.contains("франц|france", na=False)].copy()
    top3_france = (
        france_df.sort_values(by="price", ascending=False)
        [["name", "price", "year", "grape", "country"]]
        .head(3)
    )

    grape_series = (
        df["grape"].dropna().astype(str).str.split(",").explode().str.strip()
    )
    grape_series = grape_series[grape_series != ""]
    top3_grapes = grape_series.value_counts().head(3)

    dry_expensive_count = df[
        (df["sugar"].str.lower().str.contains("сух", na=False)) &
        (df["price"] > 1500)
    ].shape[0]

    price_series = df["price"].dropna()
    mode_value = price_series.mode().iloc[0] if not price_series.mode().empty else None

    stats = {
        "mode": float(mode_value) if mode_value is not None else None,
        "median": float(price_series.median()) if not price_series.empty else None,
        "mean": float(price_series.mean()) if not price_series.empty else None,
        "variance": float(price_series.var()) if not price_series.empty else None,
    }

    return {
        "top3_france": top3_france,
        "top3_grapes": top3_grapes,
        "dry_expensive_count": dry_expensive_count,
        "price_stats": stats,
    }

# =========================
# ЗАДАНИЕ 3
# =========================
def build_all_plots(filename="wine.csv"):
    df = load_and_prepare_data(filename)

    plot_paths = []

    # 1. Круговая диаграмма
    pie_path = os.path.join(PLOTS_DIR, "pie_color.png")
    plt.figure()
    df["color"].value_counts().plot.pie(autopct="%1.1f%%")
    plt.title("Распределение вин по цвету")
    plt.ylabel("")
    plt.savefig(pie_path)
    plt.close()
    plot_paths.append(("Круговая диаграмма по цвету", pie_path))

    # 2. Scatter: год vs цена
    scatter_path = os.path.join(PLOTS_DIR, "scatter_year_price.png")
    data = df.dropna(subset=["year", "price"])
    plt.figure()
    plt.scatter(data["year"], data["price"])
    plt.title("Зависимость цены от года")
    plt.xlabel("Год")
    plt.ylabel("Цена")
    plt.savefig(scatter_path)
    plt.close()
    plot_paths.append(("Точечная диаграмма: год и цена", scatter_path))

    # 3. Boxplot цены
    boxplot_path = os.path.join(PLOTS_DIR, "boxplot_price.png")
    plt.figure()
    plt.boxplot(df["price"].dropna())
    plt.title("Разброс цен")
    plt.ylabel("Цена")
    plt.savefig(boxplot_path)
    plt.close()
    plot_paths.append(("Boxplot цены", boxplot_path))

    # 4. Гистограмма сахар + страна
    hist_path = os.path.join(PLOTS_DIR, "hist_sugar_country.png")
    plt.figure()
    top_countries = df["country"].value_counts().head(5).index
    df_filtered = df[df["country"].isin(top_countries)].copy()

    unique_sugar = [x for x in df_filtered["sugar"].unique() if str(x).strip()]
    sugar_map = {v: i for i, v in enumerate(unique_sugar, start=1)}
    df_filtered["sugar_code"] = df_filtered["sugar"].map(sugar_map)

    for country in top_countries:
        subset = df_filtered[df_filtered["country"] == country]
        plt.hist(subset["sugar_code"].dropna(), alpha=0.5, label=country)

    plt.xticks(list(sugar_map.values()), list(sugar_map.keys()), rotation=20)
    plt.title("Распределение сахара по странам")
    plt.xlabel("Сахар")
    plt.ylabel("Количество")
    plt.legend()
    plt.savefig(hist_path)
    plt.close()
    plot_paths.append(("Гистограмма: сахар и страна", hist_path))

    logger.info("Графики построены")
    return plot_paths



# =========================
# ЗАДАНИЕ 4
# =========================
def run_task_4(df: pd.DataFrame):
    results = {}

    # chi2
    chi_df = df.dropna(subset=["sugar", "price"]).copy()
    chi_df["price_category"] = pd.qcut(
        chi_df["price"],
        q=3,
        labels=["Низкая", "Средняя", "Высокая"],
        duplicates="drop"
    )
    contingency_table = pd.crosstab(chi_df["sugar"], chi_df["price_category"])
    chi2, p, _, _ = chi2_contingency(contingency_table)
    results["chi2"] = {
        "chi2": float(chi2),
        "p_value": float(p),
        "conclusion": "Есть связь" if p < 0.05 else "Связи нет"
    }

    # t-test
    red = df[df["color"].str.lower().str.contains("крас", na=False)]["price"].dropna()
    white = df[df["color"].str.lower().str.contains("бел", na=False)]["price"].dropna()
    if len(red) >= 2 and len(white) >= 2:
        t_stat, p_val = ttest_ind(red, white, equal_var=False)
        results["ttest"] = {
            "t_stat": float(t_stat),
            "p_value": float(p_val),
            "conclusion": "Цены различаются" if p_val < 0.05 else "Различий нет"
        }
    else:
        results["ttest"] = {"error": "Недостаточно данных"}

    # anova
    anova_df = df.dropna(subset=["grape", "price"]).copy()
    anova_df["main_grape"] = anova_df["grape"].str.split(",").str[0].str.strip()
    counts = anova_df["main_grape"].value_counts()
    valid_grapes = counts.head(3).index
    groups = [
        anova_df[anova_df["main_grape"] == g]["price"].dropna().values
        for g in valid_grapes
    ]
    groups = [g for g in groups if len(g) >= 2]

    if len(groups) >= 2:
        f_stat, p_val = f_oneway(*groups)
        results["anova"] = {
            "f_stat": float(f_stat),
            "p_value": float(p_val),
            "conclusion": "Есть различия" if p_val < 0.05 else "Различий нет"
        }
    else:
        results["anova"] = {"error": "Недостаточно данных"}

    # correlation
    corr_df = df.dropna(subset=["year", "price"])
    if len(corr_df) >= 2:
        corr, p_val = pearsonr(corr_df["year"], corr_df["price"])
        results["correlation"] = {
            "correlation": float(corr),
            "p_value": float(p_val),
            "conclusion": "Есть зависимость" if p_val < 0.05 else "Зависимости нет"
        }
    else:
        results["correlation"] = {"error": "Недостаточно данных"}

    logger.info("Статистические тесты выполнены")
    return results

# =========================
# ФОРМАТИРОВАНИЕ ТЕКСТА ДЛЯ TG
# =========================
def format_task_2_results(results) -> str:
    lines = []
    lines.append("2 задание:\n")

    lines.append("1) Топ-3 дорогих вина из Франции:")
    if results["top3_france"].empty:
        lines.append("Нет данных")
    else:
        for _, row in results["top3_france"].iterrows():
            lines.append(f"- {row['name']} | {row['price']} ₽ | {row['year']}")

    lines.append("\n2) Топ-3 сорта винограда:")
    if results["top3_grapes"].empty:
        lines.append("Нет данных")
    else:
        for grape, count in results["top3_grapes"].items():
            lines.append(f"- {grape}: {count}")

    lines.append(f"\n3) Сухих вин дороже 1500: {results['dry_expensive_count']}")

    stats = results["price_stats"]
    lines.append("\n4) Статистика цены:")
    lines.append(f"- Мода: {stats['mode']}")
    lines.append(f"- Медиана: {stats['median']}")
    lines.append(f"- Среднее: {stats['mean']}")
    lines.append(f"- Дисперсия: {stats['variance']}")

    return "\n".join(lines)


def format_task_4_results(results) -> str:
    return (
        "4 задание:\n\n"
        f"χ² тест: {results['chi2']}\n\n"
        f"t-test: {results['ttest']}\n\n"
        f"ANOVA: {results['anova']}\n\n"
        f"Корреляция: {results['correlation']}"
    )

# =========================
# TELEGRAM BOT
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Команда /start")
    await update.message.reply_text(
        "Привет. Используй команду /vinoparsing для запуска парсинга и анализа."
    )


async def vinoparsing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Команда /vinoparsing")
    keyboard = [
        [
            InlineKeyboardButton("Да", callback_data="confirm_yes"),
            InlineKeyboardButton("Нет", callback_data="confirm_no"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Вы уверены?",
        reply_markup=reply_markup
    )

async def send_plots(chat_id, context: ContextTypes.DEFAULT_TYPE, plot_paths):
    for title, path in plot_paths:
        if os.path.exists(path):
            with open(path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=title
                )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_no":
        logger.warning("Пользователь отказался от запуска")
        await query.edit_message_text("Хорошо, я дальше спать")
        return

    if query.data == "confirm_yes":
        logger.info("Пользователь подтвердил запуск")
        await query.edit_message_text("Запускаю парсинг и анализ, подожди немного...")

        try:
            parse_all_wines(limit=50)
            df = load_and_prepare_data("wine.csv")

            task2 = task_2_analysis(df)
            plot_paths = build_all_plots("wine.csv")
            task4 = run_task_4(df)

            await query.message.reply_text(format_task_2_results(task2))

            await query.message.reply_text("3 задание выполнено. Отправляю графики:")
            await send_plots(query.message.chat_id, context, plot_paths)

            await query.message.reply_text(format_task_4_results(task4))

            logger.info("Все этапы выполнены успешно")

        except Exception as e:
            logger.critical(f"Критическая ошибка при выполнении: {e}")
            await query.message.reply_text(f"Ошибка: {e}")

# =========================
# ЗАПУСК
# =========================
def main():
    token = os.getenv("TG_BOT_TOKEN")
    if not token:
        raise ValueError("Не найден токен. Задай переменную окружения TG_BOT_TOKEN")

    logger.debug("DEBUG тест")
    logger.info("INFO запуск программы")
    logger.warning("WARNING тест")
    logger.error("ERROR тест")
    logger.critical("CRITICAL тест")

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("vinoparsing", vinoparsing))
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен")
    application.run_polling()


if __name__ == "__main__":
    main()