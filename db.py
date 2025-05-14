import json
import uuid
import sqlite3

def db_init():
    conn = sqlite3.connect("app.db")
    with open('schemas.sql') as f:
        cursor = conn.cursor()
        cursor.executescript(f.read())

def db_new_connection():

    conn = None

    try:
        conn = sqlite3.connect("app.db")
        return conn
    except sqlite3.Error as e:
        print(e)
        return None


def db_new_conversation(conn, device_id, messages, title):

    if device_id is None or device_id == "":
        print(f"[db_new_conversation] invalid device id: {device_id}")
        return

    conversation_id = str(uuid.uuid4())
    
    if title is None:
        title = "New Chat"

    if len(title) > 100:
        title = "New Chat"

    if messages is None:
        messages = []

    messages_json = json.dumps(messages)

    cursor = conn.cursor()

    try:
        
        cursor.execute("INSERT INTO conversations (id, device_id, title, messages) VALUES (?, ?, ?, ?)", 
            (conversation_id, device_id, title, messages_json))

        conn.commit()

        return {
            "conversationId": conversation_id,
            "conversationTitle": title
        }

    except sqlite3.Error as e:
        conn.rollback()
        print(f"Database error: {e}")
        return None

def db_get_conversation_list(conn, device_id):
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM conversations WHERE device_id = ?", (device_id,))
    conversation_rows = cursor.fetchall()
    conversations = []

    for conv_id, title in conversation_rows:
        conversations.append({
            "id" : conv_id,
            "title": title
        })

    return conversations

def db_get_conversation_by_id(conn, conversation_id):
    cursor = conn.cursor()
    cursor.execute("SELECT id, messages FROM conversations WHERE id = ?", (conversation_id,))
    row = cursor.fetchone()

    if row:
        messages = json.loads(row[1])
        return {
            "conversationId": row[0],
            "messages": messages
        }
    return None


def db_update_conversation_title(conn, conversation_id, new_title):
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE conversations
            SET title = ?
            WHERE id = ?
        """, (new_title, conversation_id))

        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Database error during title update: {e}")
        return False

def db_update_conversation_directory(conn, conversation_id, directory):
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE conversations
            SET directory = ?
            WHERE id = ?
        """, (directory, conversation_id))

        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Database error during directory update: {e}")
        return False

def db_update_conversation_messages(conn, conversation_id, new_messages):
    cursor = conn.cursor()
    messages_json = json.dumps(new_messages)

    try:
        cursor.execute("""
            UPDATE conversations
            SET messages = ?
            WHERE id = ?
        """, (messages_json, conversation_id))

        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Database error during messages update: {e}")
        return False

def db_delete_conversation_by_id(conn, conversation_id):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT directory FROM conversations WHERE id = ?", (conversation_id,))
        row = cursor.fetchone()
        
        if row is None:
            return None  # No conversation to delete

        directory = row[0]

        cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()
        return directory  # True if a row was deleted
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Database error during delete: {e}")
        return None
