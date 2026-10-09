import csv
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup



BASE_URL = "https://vinnayagramota.ru"
CATALOG_URL = "https://vinnayagramota.ru/vino"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
}


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def get_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_first_number(text: str) -> str:
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if match:
        return match.group(1).replace(",", ".")
    return ""


def extract_year_from_text(text: str) -> str:
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if match:
        return match.group(0)
    return ""

def extract_year(name: str, specs_block: str, page_text: str) -> str:
    """
    Ищем год по приоритету:
    1) после слова 'Урожай'
    2) в блоке характеристик
    3) в названии товара
    4) во всем тексте страницы
    """
    patterns = [
        r"Урожай[:\s]+((?:19|20)\d{2})",
        r"\b((?:19|20)\d{2})\b",
    ]

    # сначала ищем именно после 'Урожай' в блоке характеристик
    if specs_block:
        m = re.search(patterns[0], specs_block, flags=re.IGNORECASE)
        if m:
            return m.group(1)

    # потом любой год в блоке характеристик
    if specs_block:
        m = re.search(patterns[1], specs_block)
        if m:
            return m.group(1)

    # потом в названии
    if name:
        m = re.search(patterns[1], name)
        if m:
            return m.group(1)

    # в крайнем случае — по всей странице
    if page_text:
        m = re.search(patterns[0], page_text, flags=re.IGNORECASE)
        if m:
            return m.group(1)

        m = re.search(patterns[1], page_text)
        if m:
            return m.group(1)

    return ""

def extract_price(text: str) -> str:
    """
    Берем первую найденную цену вида:
    2394.00 ₽
    2,736.00
    2 736.00 ₽
    """
    text = text.replace("\xa0", " ")
    match = re.search(r"(\d[\d\s,]*\.\d{2})\s*₽", text)
    if match:
        return match.group(1).replace(" ", "").replace(",", "")
    return ""


def extract_field(block_text: str, field_name: str, stop_fields: list[str]) -> str:
    """
    Извлекает поле вида:
    Цвет: белое Сахар: сухое ...
    """
    stop_pattern = "|".join(re.escape(x) for x in stop_fields)
    pattern = rf"{re.escape(field_name)}:\s*(.*?)(?=\s+(?:{stop_pattern}):|$)"
    match = re.search(pattern, block_text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return clean_text(match.group(1))
    return ""

def get_product_links(limit=52) -> list[str]:
    soup = get_soup(CATALOG_URL)
    links = []
    seen = set()

    # слова, которые чаще всего относятся к категориям, а не к товару
    bad_parts = {
        "beloe-vino",
        "krasnoe-vino",
        "rozovoe-vino",
        "suhoe-vino",
        "polusuhoe-vino",
        "polusladkoe-vino",
        "sladkoe-vino",
        "igristoe-vino",
        "frantsiya",
        "italiya",
        "ispaniya",
        "argentina",
        "germaniya",
        "portugaliya",
        "chili",
        "rossiya",
        "novaya-zelandiya",
        "avstriya",
        "yuar",
        "armeniya",
        "gruziya",
    }

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full_url = urljoin(BASE_URL, href).split("#")[0].split("?")[0]

        if not full_url.startswith(BASE_URL + "/vino/"):
            continue

        if full_url.rstrip("/") == CATALOG_URL.rstrip("/"):
            continue

        slug = full_url.rstrip("/").split("/")[-1].lower()

        # пропускаем слишком короткие slug'и и категории
        if slug in bad_parts:
            continue

        # нам нужны именно страницы товаров;
        # у товаров почти всегда длинный slug с несколькими дефисами
        if slug.count("-") < 3:
            continue

        if full_url not in seen:
            seen.add(full_url)
            links.append(full_url)

    return links[:limit]


def get_main_text_block(soup: BeautifulSoup) -> str:
    """
    Получаем общий текст страницы.
    """
    return clean_text(soup.get_text(" ", strip=True))


def extract_specs_block(page_text: str) -> str:
    """
    Вырезаем только блок характеристик товара.
    Начинаем с 'Производитель:' или 'Цвет:'.
    Заканчиваем перед служебными блоками.
    """
    start_candidates = []
    for marker in ["Производитель:", "Цвет:"]:
        idx = page_text.find(marker)
        if idx != -1:
            start_candidates.append(idx)

    if start_candidates:
        start = min(start_candidates)
    else:
        start = 0

    end_markers = [
        "Рейтинги и награды",
        "В магазине",
        "В корзину",
        "Описание",
        "Гастрономия",
        "Отзывы",
        "Похожие товары",
    ]

    end_positions = []
    for marker in end_markers:
        idx = page_text.find(marker, start)
        if idx != -1:
            end_positions.append(idx)

    end = min(end_positions) if end_positions else len(page_text)

    return clean_text(page_text[start:end])


def parse_product_page(url: str) -> dict:
    soup = get_soup(url)
    page_text = get_main_text_block(soup)

    # Название
    h1 = soup.find("h1")
    name = clean_text(h1.get_text(" ", strip=True)) if h1 else ""

    # Только блок характеристик
    specs_block = extract_specs_block(page_text)

    # Год
    year = extract_year(name, specs_block, page_text)

    # Поля
    color = extract_field(
        specs_block,
        "Цвет",
        ["Сахар", "Виноград", "Регион", "Крепость", "Страна", "Урожай", "Объем"]
    )

    sugar = extract_field(
        specs_block,
        "Сахар",
        ["Виноград", "Регион", "Крепость", "Страна", "Урожай", "Объем"]
    )

    grape = extract_field(
        specs_block,
        "Виноград",
        ["Регион", "Крепость", "Страна", "Урожай", "Объем"]
    )

    country = extract_field(
        specs_block,
        "Страна",
        ["Урожай", "Объем", "Рейтинги и награды", "В магазине", "В корзину"]
    )

    volume = extract_field(
        specs_block,
        "Объем",
        ["Рейтинги и награды", "В магазине", "В корзину"]
    )
    volume = extract_first_number(volume) if volume else ""

    # Цена
    # Ищем первую цену уже после названия товара
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








import pandas as pd


def load_and_prepare_data(filename="wine.csv") -> pd.DataFrame:
    df = pd.read_csv(filename, encoding="utf-8-sig")

    # чистим текстовые поля
    text_columns = ["name", "color", "sugar", "grape", "country"]
    for col in text_columns:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    # приводим числовые поля
    for col in ["price", "year", "volume"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", ".", regex=False)
                .str.extract(r"(\d+(?:\.\d+)?)")[0]
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def task_2_analysis(df: pd.DataFrame):
    results = {}

    # 1. Топ-3 вин с самой большой ценой из Франции
    france_df = df[
        df["country"].str.lower().str.contains("франц", na=False)
    ].copy()

    top3_france = (
        france_df
        .sort_values(by="price", ascending=False)
        [["name", "price", "year", "grape", "country"]]
        .head(3)
    )

    results["top3_france"] = top3_france

    # 2. Топ-3 самых частых сортов винограда
    grape_series = (
        df["grape"]
        .dropna()
        .astype(str)
        .str.split(",")
        .explode()
        .str.strip()
    )

    grape_series = grape_series[grape_series != ""]

    top3_grapes = grape_series.value_counts().head(3)
    results["top3_grapes"] = top3_grapes

    # 3. Количество сухих вин с ценой более 1500 рублей
    dry_expensive_count = df[
        (df["sugar"].str.lower().str.contains("сух", na=False)) &
        (df["price"] > 1500)
    ].shape[0]

    results["dry_expensive_count"] = dry_expensive_count

    # 4. Мода, медиана, среднее и дисперсия цены
    price_series = df["price"].dropna()

    mode_value = price_series.mode()
    mode_value = mode_value.iloc[0] if not mode_value.empty else None

    stats = {
        "mode": mode_value,
        "median": price_series.median(),
        "mean": price_series.mean(),
        "variance": price_series.var()
    }

    results["price_stats"] = stats

    return results

def print_task_2_results(results):
    print("\n=== 2 задание ===")

    print("\n1. Топ-3 вин с самой большой ценой из Франции:")
    if not results["top3_france"].empty:
        print(results["top3_france"].to_string(index=False))
    else:
        print("Нет данных по винам из Франции.")

    print("\n2. Топ-3 самых частых сортов винограда:")
    if not results["top3_grapes"].empty:
        print(results["top3_grapes"].to_string())
    else:
        print("Нет данных по сортам винограда.")

    print("\n3. Количество сухих вин с ценой более 1500 рублей:")
    print(results["dry_expensive_count"])

    print("\n4. Статистика цены:")
    print(f"Мода: {results['price_stats']['mode']}")
    print(f"Медиана: {results['price_stats']['median']}")
    print(f"Среднее: {results['price_stats']['mean']}")
    print(f"Дисперсия: {results['price_stats']['variance']}")


def main():
    print("Собираю ссылки на товары...")
    links = get_product_links(limit=10)
    print(f"Найдено карточек товаров: {len(links)}")

    for link in links[:5]:
        print("LINK:", link)

    rows = []
    seen = set()

    for i, link in enumerate(links, start=1):
        try:
            print(f"[{i}/{len(links)}] {link}")
            row = parse_product_page(link)

            key = (row["name"], row["price"])
            if row["name"] and key not in seen:
                seen.add(key)
                rows.append(row)

            time.sleep(0.3)

        except Exception as e:
            print(f"Ошибка при обработке {link}: {e}")

    save_to_csv(rows, "wine.csv")
    print(f"Готово. Сохранено {len(rows)} строк в wine.csv")
    df = load_and_prepare_data("wine.csv")
    results = task_2_analysis(df)
    print_task_2_results(results)

if __name__ == "__main__":
    main()

#3 задание поехали
import pandas as pd
import matplotlib.pyplot as plt
import os


def load_data_for_plots(filename="wine.csv"):
    df = pd.read_csv(filename, encoding="utf-8-sig")

    # чистка
    for col in ["name", "color", "sugar", "grape", "country"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    for col in ["price", "year", "volume"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.extract(r"(\d+(?:\.\d+)?)")[0]
        )
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df

# круговая диграма шняга
def plot_color_pie(df):
    plt.figure()

    color_counts = df["color"].value_counts()

    color_counts.plot.pie(
        autopct="%1.1f%%"
    )

    plt.title("Распределение вин по цвету")
    plt.ylabel("")

    plt.savefig("plots/круговая_диаграмма.png")
    plt.close()

# точнечная диаграмма шняга год vs цена
def plot_year_price_scatter(df):
    data = df.dropna(subset=["year", "price"])

    plt.figure()
    plt.scatter(data["year"], data["price"])

    plt.title("Зависимость цены от года")
    plt.xlabel("Год")
    plt.ylabel("Цена")

    plt.savefig("plots/точечная_диаграмма_год_цена.png")
    plt.close()


# разброс цен
def plot_price_boxplot(df):
    plt.figure()

    plt.boxplot(df["price"].dropna())

    plt.title("Разброс цен")
    plt.ylabel("Цена")

    plt.savefig("plots/разброс_цен.png")
    plt.close()

#многостолбиковая диаграмма количество вин по странам
def plot_sugar_country_hist(df):
    plt.figure()

    # берём топ-5 стран
    top_countries = df["country"].value_counts().head(5).index

    df_filtered = df[df["country"].isin(top_countries)].copy()

    # кодируем сахар
    sugar_map = {v: i for i, v in enumerate(df_filtered["sugar"].unique(), start=1)}
    df_filtered["sugar_code"] = df_filtered["sugar"].map(sugar_map)

    for country in top_countries:
        subset = df_filtered[df_filtered["country"] == country]
        plt.hist(subset["sugar_code"].dropna(), alpha=0.5, label=country)

    plt.xticks(list(sugar_map.values()), list(sugar_map.keys()), rotation=20)

    plt.title("Распределение сахара по странам")
    plt.xlabel("Сахар")
    plt.ylabel("Количество")
    plt.legend()

    plt.savefig("plots/многослойная_гистограмма.png")
    plt.close()

def build_all_plots():
    if not os.path.exists("plots"):
        os.makedirs("plots")

    df = load_data_for_plots("wine.csv")

    plot_color_pie(df)
    plot_year_price_scatter(df)
    plot_price_boxplot(df)
    plot_sugar_country_hist(df)

    print("Графики сохранены в папке plots/")


if __name__ == "__main__":
    build_all_plots()




#4 задание летс гоу
import pandas as pd
from scipy.stats import chi2_contingency, ttest_ind, f_oneway, pearsonr


def load_data_for_stats(filename="wine.csv"):
    df = pd.read_csv(filename, encoding="utf-8-sig")

    for col in ["name", "color", "sugar", "grape", "country"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    for col in ["price", "year", "volume"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.extract(r"(\d+(?:\.\d+)?)")[0]
        )
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


#х2 тест на сахар и цену
def chi_square_test(df):
    df = df.dropna(subset=["sugar", "price"]).copy()

    # разбиваем цену на категории
    df["price_category"] = pd.qcut(
        df["price"],
        q=3,
        labels=["Низкая", "Средняя", "Высокая"],
        duplicates="drop"
    )

    contingency_table = pd.crosstab(df["sugar"], df["price_category"])

    chi2, p, dof, expected = chi2_contingency(contingency_table)

    return {
        "chi2": chi2,
        "p_value": p,
        "conclusion": "Есть связь" if p < 0.05 else "Связи нет"
    }

# т тест для красных и белых вин по цене
def t_test_colors(df):
    red = df[df["color"].str.lower().str.contains("крас")]["price"].dropna()
    white = df[df["color"].str.lower().str.contains("бел")]["price"].dropna()

    if len(red) < 2 or len(white) < 2:
        return {"error": "Недостаточно данных"}

    t_stat, p = ttest_ind(red, white, equal_var=False)

    return {
        "t_stat": t_stat,
        "p_value": p,
        "conclusion": "Цены различаются" if p < 0.05 else "Различий нет"
    }

# ANOVA для разных стран по цене
def anova_grape(df):
    df = df.dropna(subset=["grape", "price"]).copy()

    df["main_grape"] = df["grape"].str.split(",").str[0].str.strip()

    counts = df["main_grape"].value_counts()

    # берем топ-3 самых частых сорта
    valid_grapes = counts.head(3).index

    groups = [
        df[df["main_grape"] == g]["price"].dropna().values
        for g in valid_grapes
    ]

    # оставляем только группы >=2 элементов
    groups = [g for g in groups if len(g) >= 2]

    if len(groups) < 2:
        return {"error": "Недостаточно данных"}

    from scipy.stats import f_oneway
    f_stat, p = f_oneway(*groups)

    return {
        "f_stat": float(f_stat),
        "p_value": float(p),
        "conclusion": "Есть различия" if p < 0.05 else "Различий нет"
    }

# корреляция между годом и ценой
def correlation_year_price(df):
    df = df.dropna(subset=["year", "price"])

    if len(df) < 2:
        return {"error": "Недостаточно данных"}

    corr, p = pearsonr(df["year"], df["price"])

    return {
    "correlation": float(corr),
    "p_value": float(p),
    "conclusion": (
        "Есть зависимость" if p < 0.05 else "Зависимости нет"
    )
}

def run_task_4():
    df = load_data_for_stats("wine.csv")

    chi2_res = chi_square_test(df)
    ttest_res = t_test_colors(df)
    anova_res = anova_grape(df)
    corr_res = correlation_year_price(df)

    print("\n=== 4 ЗАДАНИЕ ===")

    print("\nχ² тест:")
    print(chi2_res)

    print("\nt-test (красные vs белые):")
    print(ttest_res)

    print("\nANOVA (виноград):")
    print(anova_res)

    print("\nКорреляция (год vs цена):")
    print(corr_res)

if __name__ == "__main__":
    run_task_4()

