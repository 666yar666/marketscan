import asyncio
import requests
import pandas as pd
import streamlit as st
from cleaner import DataCleaner
from parsers.olx import OLXParser
from parsers.prom import PromParser
from parsers.rozetka import RozetkaParser
from parsers.hotline import HotlineParser
from parsers.ebay import EbayParser
import json
import os
import database
from translations import TRANSLATIONS
from google_auth_oauthlib.flow import Flow

CLIENT_SECRETS_FILE = "client_secret.json"
REDIRECT_URI = "http://localhost:8501"

def get_google_auth_flow():
    """Создает и возвращает объект авторизационного потока Google OAuth."""
    scopes = [
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email",
        "openid"
    ]
    
    use_secrets = False
    try:
        if "google_oauth" in st.secrets:
            use_secrets = True
    except Exception:
        pass
        
    if use_secrets:
        client_config = {"web": dict(st.secrets["google_oauth"])}
        return Flow.from_client_config(
            client_config,
            scopes=scopes,
            redirect_uri=st.secrets["google_oauth"]["redirect_uris"][0]
        )
    else:
        return Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=scopes,
            redirect_uri=REDIRECT_URI
        )

def save_verifier(state: str, verifier: str):
    data = {}
    if os.path.exists(".oauth_state.json"):
        try:
            with open(".oauth_state.json", "r") as f:
                data = json.load(f)
        except Exception:
            pass
    data[state] = verifier
    with open(".oauth_state.json", "w") as f:
        json.dump(data, f)

def get_verifier(state: str) -> str:
    if os.path.exists(".oauth_state.json"):
        try:
            with open(".oauth_state.json", "r") as f:
                data = json.load(f)
                return data.get(state)
        except Exception:
            pass
    return None

# --- НАСТРОЙКА СТРАНИЦЫ ---
st.set_page_config(
    page_title="Marketplace Scanner",
    page_icon="🛒",
    layout="wide",
)

lang = st.sidebar.radio("Language / Язык / Мова", ["🇷🇺 Русский", "🇬🇧 English", "🇺🇦 Українська"])
t = TRANSLATIONS[lang]
st.sidebar.markdown("---")

st.title(t["title"])
st.markdown(t["subtitle"])

# Маппинг парсеров
PARSER_MAP = {
    "OLX": OLXParser,
    "Prom": PromParser,
    "Rozetka": RozetkaParser,
    "Hotline": HotlineParser,
    "eBay": EbayParser,
}


# --- КУРС НБУ ---
@st.cache_data(ttl=3600)
def get_usd_rate() -> float:
    """Получает курс USD/UAH от НБУ. Кэшируется на 1 час.
    
    При ошибке возвращает хардкод-значение 41.5.
    """
    try:
        response = requests.get(
            "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json",
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        for entry in data:
            if entry.get("cc") == "USD":
                return float(entry["rate"])
    except Exception:
        pass
    return 41.5  # fallback


def convert_prices(items: list, target_currency: str, usd_rate: float) -> list:
    """Конвертирует цены всех товаров в целевую валюту."""
    import copy
    converted = []
    for item in items:
        obj = copy.copy(item)
        if target_currency == "UAH" and obj.currency == "USD":
            obj.price = round(obj.price * usd_rate, 2)
            obj.currency = "UAH"
        elif target_currency == "USD" and obj.currency == "UAH":
            obj.price = round(obj.price / usd_rate, 2)
            obj.currency = "USD"
        converted.append(obj)
    return converted


# --- АСИНХРОННАЯ ФУНКЦИЯ СБОРА ---
async def scrape_all(query: str, active_markets: list[str]):
    tasks = []
    for market_name in active_markets:
        if market_name in PARSER_MAP:
            parser_instance = PARSER_MAP[market_name]()
            tasks.append(parser_instance.fetch_data(query))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items = []
    for res in results:
        if isinstance(res, list):
            all_items.extend(res)
    return all_items


# --- ПРОЦЕССИНГ GOOGLE OAUTH ---
if "code" in st.query_params:
    code = st.query_params["code"]
    state = st.query_params.get("state")
    
    try:
        flow = get_google_auth_flow()
        
        # ⚠️ ВОССТАНАВЛИВАЕМ проверочный код из серверного кэша по state
        if state:
            verifier = get_verifier(state)
            if verifier:
                flow.code_verifier = verifier

        flow.fetch_token(code=code)
        
        session = flow.authorized_session()
        user_info = session.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
        
        st.session_state["logged_in"] = True
        st.session_state["username"] = user_info.get("name", "User")
        st.session_state["user_info"] = user_info
        
        # Очищаем временный verifier и параметры URL
        if "code_verifier" in st.session_state:
            del st.session_state["code_verifier"]
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(t["auth_error"].format(error=e))

# --- ИНТЕРФЕЙС УПРАВЛЕНИЯ (Сайдбар) ---
with st.sidebar:
    # --- СИСТЕМА АВТОРИЗАЦИИ ---
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["username"] = ""

    if not st.session_state["logged_in"]:
        st.header(t["auth_title"])
        auth_mode = st.radio(t["choose_action"], [t["login_radio"], t["register_radio"], t["google_radio"]])
        
        if auth_mode == t["google_radio"]:
            st.write(t["login_with_google_prompt"])
            try:
                flow = get_google_auth_flow()
                auth_url, state = flow.authorization_url(prompt="consent")
                
                # ⚠️ СОХРАНЯЕМ проверочный код на сервере с привязкой к state
                if hasattr(flow, 'code_verifier'):
                    save_verifier(state, flow.code_verifier)
                
                # HTML кнопка с target="_self" чтобы не открывать новую вкладку
                button_html = f"""
                <a href="{auth_url}" target="_self" style="
                    display: block; 
                    width: 100%; 
                    text-align: center; 
                    background-color: #ff4b4b; 
                    color: white; 
                    padding: 0.5rem 1rem; 
                    border-radius: 0.5rem; 
                    text-decoration: none; 
                    font-weight: 600; 
                    margin-top: 10px;">
                    {t["login_with_google_btn"]}
                </a>
                """
                st.markdown(button_html, unsafe_allow_html=True)
            except Exception as e:
                st.error(t["secrets_not_found"])
        else:
            with st.form("auth_form"):
                username = st.text_input(t["username"])
                if auth_mode == t["register_radio"]:
                    email = st.text_input(t["email"])
                password = st.text_input(t["password"], type="password")
                submit = st.form_submit_button(auth_mode)
                
                if submit:
                    if auth_mode == t["login_radio"]:
                        if database.authenticate_user(username, password):
                            st.session_state["logged_in"] = True
                            st.session_state["username"] = username
                            st.success(t["login_success"])
                            st.rerun()
                        else:
                            st.error(t["login_error"])
                    else:
                        if database.add_user(username, email, password):
                            st.success(t["register_success"])
                        else:
                            st.error(t["register_error"])
        
        st.info(t["auth_prompt"])
        st.stop()  # Прерываем выполнение скрипта, если пользователь не авторизован
    else:
        st.header(t["hello_user"].format(name=st.session_state['username']))
        
        if "user_info" in st.session_state:
            picture_url = st.session_state["user_info"].get("picture")
            if picture_url and isinstance(picture_url, str) and picture_url.startswith("http"):
                st.image(picture_url, width=80)
            
        if st.button(t["logout"], use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["username"] = ""
            if "user_info" in st.session_state:
                del st.session_state["user_info"]
            st.rerun()
            
    st.markdown("---")

    st.header(t["search_settings"])

    # 1. Выбор маркетплейсов
    selected_markets = st.multiselect(
        t["markets_label"],
        options=list(PARSER_MAP.keys()),
        default=["OLX", "Prom", "Rozetka", "Hotline", "eBay"],
        help=t["markets_help"],
    )

    st.markdown("---")

    # 2. Фильтр цены
    min_price = st.number_input(
        t["min_price_label"].format(currency=currency_symbol if 'currency_symbol' in locals() else '₴'),
        value=3000,
        step=500,
        help=t["min_price_help"],
    )

    st.markdown("---")

    # 3. Валюта отображения
    usd_rate = get_usd_rate()
    display_currency = st.radio(
        t["currency_label_text"],
        ["UAH", "USD"],
        help=t["nbu_rate"].format(rate=usd_rate),
    )
    st.caption(t["nbu_rate"].format(rate=usd_rate))

    st.markdown("---")
    st.info(t["advice_text"])

# Символ валюты для интерфейса
currency_symbol = "₴" if display_currency == "UAH" else "$"

# Теперь можно обновить min_price_label, если нужно (но number_input уже отрендерился,
# поэтому мы просто можем оставить (₴) или использовать display_currency, 
# но в оригинале было просто "Минимальная цена (₴)". В словаре есть {currency})

# --- ГЛАВНЫЙ ЭКРАН (Поиск) ---
query = st.text_input(t["search_input_label"], placeholder=t["search_input_placeholder"])
search_button = st.button(t["search_btn"], type="primary", use_container_width=True)

if search_button and query:
    if not selected_markets:
        st.warning(t["no_market_warning"])
        st.stop()

    with st.spinner(t["searching_spinner"].format(query=query, markets=", ".join(selected_markets))):
        # 1. Запуск парсеров
        raw_items = asyncio.run(scrape_all(query, selected_markets))

        if not raw_items:
            st.error(t["nothing_found"])
            st.stop()

        # 2. Очистка и фильтрация
        cleaner = DataCleaner(min_price=float(min_price), usd_rate=usd_rate)
        cleaned_items = cleaner.process(raw_items, query=query)

        if not cleaned_items:
            st.warning(t["all_too_cheap"].format(min_price=min_price))
            st.stop()

        # 3. Конвертация валюты
        converted_items = convert_prices(cleaned_items, display_currency, usd_rate)

        # 4. Преобразование в DataFrame
        df = pd.DataFrame([item.__dict__ for item in converted_items])

        # Нормализация наименований для интерфейса
        df["marketplace"] = df["source"].str.upper()
        df["condition"] = df["condition"].str.upper()

        df_new = df[df["condition"] == "NEW"]
        df_used = df[df["condition"] == "USED"]

        # --- ВЫВОД СТАТИСТИКИ ---
        st.subheader(t["market_analysis"])
        col1, col2 = st.columns(2)

        with col1:
            st.markdown(t["new_items"])
            if not df_new.empty:
                median_new = df_new["price"].median()
                min_new = df_new["price"].min()
                max_new = df_new["price"].max()
                if display_currency == "UAH":
                    st.metric(t["median_price"], f"{int(median_new):,} ₴".replace(",", " "))
                    st.caption(t["found_count_range_uah"].format(count=len(df_new), min_val=f"{int(min_new):,}".replace(",", " "), max_val=f"{int(max_new):,}".replace(",", " ")))
                else:
                    st.metric(t["median_price"], f"${median_new:,.2f}")
                    st.caption(t["found_count_range_usd"].format(count=len(df_new), min_val=f"{min_new:,.2f}", max_val=f"{max_new:,.2f}"))
            else:
                st.info(t["new_items_not_found"])

        with col2:
            st.markdown(t["used_items"])
            if not df_used.empty:
                median_used = df_used["price"].median()
                min_used = df_used["price"].min()
                max_used = df_used["price"].max()
                if display_currency == "UAH":
                    st.metric("Медианная цена", f"{int(median_used):,} ₴".replace(",", " "))
                    st.caption(f"Найдено: {len(df_used)} шт. | Диапазон: {int(min_used):,} – {int(max_used):,} ₴".replace(",", " "))
                else:
                    st.metric("Медианная цена", f"${median_used:,.2f}")
                    st.caption(f"Найдено: {len(df_used)} шт. | Диапазон: ${min_used:,.2f} – ${max_used:,.2f}")
            else:
                st.info("Б/У товаров не найдено")

        st.divider()

        # --- ГРАФИК ЦЕН ---
        st.subheader(t["price_distribution"].format(currency=display_currency))
        st.scatter_chart(
            df,
            x="marketplace",
            y="price",
            color="condition",
            size=100,
        )

        st.divider()

        # --- ТАБЛИЦА С ТОВАРАМИ ---
        price_col_label = t["col_price"].format(currency=currency_symbol)
        price_format = "%d" if display_currency == "UAH" else "%.2f"

        st.subheader(t["found_items_list"])
        st.dataframe(
            df[["title", "price", "marketplace", "condition", "url"]].sort_values(by="price"),
            column_config={
                "title": t["col_title"],
                "price": st.column_config.NumberColumn(
                    price_col_label,
                    format=f"{currency_symbol}%d" if display_currency == "UAH" else "$%.2f",
                ),
                "marketplace": t["col_market"],
                "condition": t["col_condition"],
                "url": st.column_config.LinkColumn(t["col_url"]),
            },
            hide_index=True,
            use_container_width=True,
        )
