import sqlite3
import bcrypt

DB_NAME = "users.db"

def init_db():
    """Создает базу данных и таблицу пользователей, если они не существуют."""
    conn = sqlite3.connect(DB_NAME)
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
    conn.close()

def add_user(username: str, email: str, password: str) -> bool:
    """Регистрирует нового пользователя. Возвращает True, если успешно, False если такой пользователь уже есть."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Хэшируем пароль
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
        
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, password_hash)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Пользователь с таким именем или email уже существует
        return False
    finally:
        conn.close()

def authenticate_user(username: str, password: str) -> bool:
    """Проверяет логин и пароль пользователя."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        stored_hash = result[0].encode('utf-8')
        # Сравниваем предоставленный пароль с хэшем из БД
        if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
            return True
            
    return False

# Инициализируем БД при импорте модуля
init_db()
