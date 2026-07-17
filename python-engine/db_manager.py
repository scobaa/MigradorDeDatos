import sqlite3
import os
import hashlib
import binascii
import uuid
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "migrador.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS clients (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        odoo_url TEXT NOT NULL,
        odoo_db TEXT NOT NULL,
        odoo_user TEXT NOT NULL,
        odoo_password TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_used_at DATETIME,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )''')
    
    # Tabla templates por si acaso (para igualar el frontend DBTemplate)
    conn.execute('''CREATE TABLE IF NOT EXISTS templates (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        source_type TEXT NOT NULL,
        mapping_count INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )''')
    
    conn.commit()
    conn.close()

# Aseguramos que la DB esté creada al importar
init_db()

def hash_password(password: str) -> str:
    """Crea un hash seguro de la contraseña."""
    salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
    pwdhash = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000)
    pwdhash = binascii.hexlify(pwdhash)
    return (salt + pwdhash).decode('ascii')

def verify_password(stored_password: str, provided_password: str) -> bool:
    """Verifica la contraseña contra el hash almacenado."""
    try:
        salt = stored_password[:64]
        stored_pwdhash = stored_password[64:]
        pwdhash = hashlib.pbkdf2_hmac('sha512', provided_password.encode('utf-8'), salt.encode('ascii'), 100000)
        pwdhash = binascii.hexlify(pwdhash).decode('ascii')
        return pwdhash == stored_pwdhash
    except Exception:
        return False

# --- AUTH FUNCIONES ---

def register_user(email: str, password: str) -> str:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cur.fetchone():
            raise ValueError("El correo ya está registrado.")
            
        pwd_hash = hash_password(password)
        cur.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, pwd_hash))
        user_id = cur.lastrowid
        
        token = str(uuid.uuid4())
        cur.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        
        conn.commit()
        return token
    finally:
        conn.close()

def login_user(email: str, password: str) -> str:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        
        if not row or not verify_password(row["password_hash"], password):
            raise ValueError("Correo o contraseña incorrectos.")
            
        user_id = row["id"]
        token = str(uuid.uuid4())
        cur.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        
        conn.commit()
        return token
    finally:
        conn.close()

def logout_user(token: str) -> bool:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def get_user_id(token: str) -> int:
    """Devuelve el user_id a partir del token, o lanza error."""
    if not token:
        raise PermissionError("No autorizado. Token no proporcionado.")
        
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
        row = cur.fetchone()
        if not row:
            raise PermissionError("Sesión inválida o expirada.")
        return row["user_id"]
    finally:
        conn.close()


def get_user_email(token: str) -> str | None:
    """Devuelve el email del usuario asociado al token, o None si no existe."""
    if not token:
        return None
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT u.email FROM users u INNER JOIN sessions s ON s.user_id = u.id WHERE s.token = ?",
            (token,),
        )
        row = cur.fetchone()
        return row["email"] if row else None
    except Exception:
        return None
    finally:
        conn.close()

# --- CLIENTES FUNCIONES ---

def get_clients(token: str) -> list[dict]:
    user_id = get_user_id(token)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM clients WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def add_client(token: str, client_data: dict) -> dict:
    user_id = get_user_id(token)
    
    # Generar ID y fechas
    client_id = str(int(datetime.datetime.now().timestamp() * 1000))
    created_at = datetime.datetime.now().strftime("%Y-%m-%d")
    last_used_at = "Nunca"
    
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO clients (id, user_id, name, odoo_url, odoo_db, odoo_user, odoo_password, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            client_id, user_id, 
            client_data.get("name", "Sin Nombre"),
            client_data.get("odoo_url", ""),
            client_data.get("odoo_db", ""),
            client_data.get("odoo_user", ""),
            client_data.get("odoo_password", ""),
            created_at, last_used_at
        ))
        conn.commit()
        
        # Devolvemos el registro guardado
        cur.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        return dict(cur.fetchone())
    finally:
        conn.close()

def update_client(token: str, client_id: str, client_data: dict) -> dict:
    user_id = get_user_id(token)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute('''
            UPDATE clients 
            SET name = ?, odoo_url = ?, odoo_db = ?, odoo_user = ?, odoo_password = ?
            WHERE id = ? AND user_id = ?
        ''', (
            client_data.get("name", "Sin Nombre"),
            client_data.get("odoo_url", ""),
            client_data.get("odoo_db", ""),
            client_data.get("odoo_user", ""),
            client_data.get("odoo_password", ""),
            client_id, user_id
        ))
        conn.commit()
        
        if cur.rowcount == 0:
            raise ValueError("Cliente no encontrado o sin permisos")
            
        cur.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        return dict(cur.fetchone())
    finally:
        conn.close()

def delete_client(token: str, client_id: str) -> bool:
    user_id = get_user_id(token)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM clients WHERE id = ? AND user_id = ?", (client_id, user_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def update_client_last_used(token: str, client_id: str) -> bool:
    user_id = get_user_id(token)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE clients SET last_used_at = ? WHERE id = ? AND user_id = ?", (today, client_id, user_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
