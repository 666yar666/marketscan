import sqlite3
import bcrypt

DB_NAME = "users.db"

def get_connection():
    """Возвращает новое подключение к SQLite с таймаутом 20 секунд."""
    return sqlite3.connect(DB_NAME, timeout=20.0)

def init_db():
    """Создает базу данных и таблицу пользователей, если они не существуют."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                subscription_status TEXT DEFAULT 'free'
            )
        ''')
        conn.commit()

def add_user(username: str, email: str, password: str) -> bool:
    """Регистрирует нового пользователя. Возвращает True, если успешно, False если такой пользователь уже есть."""
    try:
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                (username, email, password_hash)
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        # Пользователь с таким именем или email уже существует
        return False
    except Exception:
        return False

def authenticate_user(username: str, password: str) -> bool:
    """Проверяет логин и пароль пользователя."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        result = cursor.fetchone()
    
    if result:
        stored_hash = result[0].encode('utf-8')
        # Сравниваем предоставленный пароль с хэшем из БД
        if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
            return True
            
    return False

# Инициализируем БД при импорте модуля
init_db()
