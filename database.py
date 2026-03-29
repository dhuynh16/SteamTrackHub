import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from mysql.connector import errorcode

def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='H1rrison1029!',
        database='steamtrack_hub'
    )

# ====================== REGISTER / LOGIN ======================
def register_user(username, email, password, role='user'):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
    try:
        cursor.execute(
            "INSERT INTO Users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            (username, email, hashed_pw, role)
        )
        conn.commit()
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_DUP_ENTRY:
            raise ValueError("Email already in use. Please choose a different email or log in.")
        else:
            raise
    finally:
        cursor.close()
        conn.close()

def login_user(email, password):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None

# ====================== LIBRARY (UPDATED with search/filter) ======================
def get_user_library(user_id, search_term=None, status_filter=None, genre_filter=None, favorite_only=False):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT ug.user_game_id, g.game_id, g.title, g.genre, ug.status, 
               ug.hours_played, ug.completion_date, ug.notes, ug.is_favorite
        FROM User_Games ug
        JOIN Games g ON ug.game_id = g.game_id
        WHERE ug.user_id = %s
    """
    params = [user_id]

    if search_term:
        query += " AND g.title LIKE %s"
        params.append(f"%{search_term}%")
    if status_filter:
        query += " AND ug.status = %s"
        params.append(status_filter)
    if genre_filter:
        query += " AND g.genre = %s"
        params.append(genre_filter)
    if favorite_only:
        query += " AND ug.is_favorite = 1"

    query += " ORDER BY g.title"
    cursor.execute(query, tuple(params))
    library = cursor.fetchall()
    cursor.close()
    conn.close()
    return library

# ====================== FAVORITE + UPDATE ======================
def toggle_favorite(user_game_id, user_id, is_favorite):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE User_Games SET is_favorite = %s WHERE user_game_id = %s AND user_id = %s",
        (is_favorite, user_game_id, user_id)
    )
    conn.commit()
    cursor.close()
    conn.close()

def update_game_status(user_game_id, user_id, status, hours_played, notes, completion_date, is_favorite):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE User_Games 
        SET status = %s, hours_played = %s, notes = %s, 
            completion_date = %s, is_favorite = %s
        WHERE user_game_id = %s AND user_id = %s
    """, (status, hours_played, notes, completion_date, is_favorite, user_game_id, user_id))
    conn.commit()
    cursor.close()
    conn.close()

# ====================== AI RECOMMENDATION BOT ======================
def get_ai_recommendations(user_id, limit=6):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT g.genre, COUNT(*) as cnt
        FROM User_Games ug
        JOIN Games g ON ug.game_id = g.game_id
        WHERE ug.user_id = %s AND g.genre IS NOT NULL
        GROUP BY g.genre
        ORDER BY cnt DESC LIMIT 3
    """, (user_id,))
    user_genres = [row['genre'] for row in cursor.fetchall()]

    if not user_genres:
        cursor.execute("""
            SELECT g.game_id, g.title, g.genre
            FROM Games g
            LEFT JOIN User_Games ug ON g.game_id = ug.game_id AND ug.user_id = %s
            WHERE ug.user_game_id IS NULL
            ORDER BY RAND() LIMIT %s
        """, (user_id, limit))
    else:
        placeholders = ','.join(['%s'] * len(user_genres))
        cursor.execute(f"""
            SELECT g.game_id, g.title, g.genre
            FROM Games g
            LEFT JOIN User_Games ug ON g.game_id = ug.game_id AND ug.user_id = %s
            WHERE ug.user_game_id IS NULL 
              AND g.genre IN ({placeholders})
            ORDER BY RAND() LIMIT %s
        """, [user_id] + user_genres + [limit])
    
    recs = cursor.fetchall()
    cursor.close()
    conn.close()
    return recs

# ====================== ALL ORIGINAL FUNCTIONS (required by app.py) ======================
def get_active_challenges():
    return [
        {"id": 1, "name": "100 Hours Challenge", "description": "Play 100 hours this month"},
        {"id": 2, "name": "Complete 5 Games", "description": "Finish 5 games before end of month"}
    ]

def get_leaderboard(limit=50):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT username, points FROM Users ORDER BY points DESC LIMIT %s", (limit,))
    board = cursor.fetchall()
    cursor.close()
    conn.close()
    return board

def get_pending_reviews():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT r.review_id, u.username, g.title, r.review_text, r.score, r.created_at
        FROM Reviews r
        JOIN Users u ON r.user_id = u.user_id
        JOIN Games g ON r.game_id = g.game_id
        WHERE r.approved = 0
        ORDER BY r.created_at DESC
    """)
    reviews = cursor.fetchall()
    cursor.close()
    conn.close()
    return reviews

def moderate_review(review_id, approve=True):
    conn = get_db_connection()
    cursor = conn.cursor()
    if approve:
        cursor.execute("UPDATE Reviews SET approved = 1 WHERE review_id = %s", (review_id,))
    else:
        cursor.execute("DELETE FROM Reviews WHERE review_id = %s", (review_id,))
    conn.commit()
    cursor.close()
    conn.close()

def join_challenge(user_id, challenge_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT IGNORE INTO User_Challenges (user_id, challenge_id, progress) VALUES (%s, %s, 0)", (user_id, challenge_id))
    conn.commit()
    cursor.close()
    conn.close()

def update_challenge_progress(user_id, challenge_id, increment=1):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE User_Challenges SET progress = progress + %s WHERE user_id = %s AND challenge_id = %s",
        (increment, user_id, challenge_id)
    )
    conn.commit()
    rows_updated = cursor.rowcount
    cursor.close()
    conn.close()
    return rows_updated > 0

def check_challenge_completion(user_id, challenge_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT uc.progress, c.goal, c.reward_points "
        "FROM User_Challenges uc "
        "JOIN Challenges c ON uc.challenge_id = c.challenge_id "
        "WHERE uc.user_id = %s AND uc.challenge_id = %s",
        (user_id, challenge_id)
    )
    data = cursor.fetchone()
    cursor.close()
    conn.close()
    if data and data['progress'] >= data['goal']:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET points = points + %s WHERE user_id = %s", (data['reward_points'], user_id))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    return False

def insert_review(user_id, game_id, review_text, score):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Reviews (user_id, game_id, review_text, score) VALUES (%s, %s, %s, %s)",
        (user_id, game_id, review_text, score)
    )
    conn.commit()
    cursor.close()
    conn.close()
    print(f"Notification sent to followers for review on game {game_id} by user {user_id}")
