import os
import sys

engine_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, engine_dir)

import db_manager
from email_notifier import is_configured, _get_smtp_config

def main():
    print("=== TEST EMAIL CONFIG ===")
    
    # 1. Test SMTP config
    configured = is_configured()
    print(f"SMTP Configured: {configured}")
    if configured:
        cfg = _get_smtp_config()
        print(f"SMTP Host: {cfg['host']}")
        print(f"SMTP Port: {cfg['port']}")
        print(f"SMTP User: {cfg['user']}")
        print(f"SMTP From: {cfg['from_addr']}")
        print(f"SMTP Password length: {len(cfg['password'])}")
        print(f"SMTP TLS: {cfg['use_tls']}")
    else:
        print("ERROR: SMTP config not loaded or missing fields. Check .env")

    # 2. Test DB users
    print("\n=== DB USERS AND TOKENS ===")
    conn = db_manager.get_db()
    cur = conn.cursor()
    cur.execute("SELECT u.id, u.email, s.token FROM users u LEFT JOIN sessions s ON s.user_id = u.id")
    users = cur.fetchall()
    
    if not users:
        print("No users found in DB!")
        
    for row in users:
        token = row['token']
        email = row['email']
        print(f"User ID: {row['id']} | Email: {email} | Token: {token[:8] if token else None}...")
        
        if token:
            extracted_email = db_manager.get_user_email(token)
            print(f"  -> get_user_email('{token[:8]}...'): {extracted_email}")

if __name__ == "__main__":
    main()
