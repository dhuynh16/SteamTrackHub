from flask import Flask, render_template, request, session, redirect, url_for
from database import register_user, login_user, get_pending_reviews, moderate_review, get_user_library, join_challenge, get_leaderboard
from database import get_db_connection, toggle_favorite, update_game_status, get_ai_recommendations
import requests
from database import insert_review

app = Flask(__name__)
app.secret_key = 'super_secret_key_change_me_later'

@app.route('/')
def home():
    return '<h1>Flask is alive! Go to /register</h1>'

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        try:
            register_user(username, email, password)
            return redirect(url_for('login'))
        except ValueError as e:
            error = str(e)
        except Exception as e:
            error = "An unexpected error occurred. Please try again."
    return render_template('register.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    print("→ /login route was called (method:", request.method, ")")
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = login_user(email, password)
        if user:
            session['user_id'] = user['user_id']
            session['username'] = user['username']   # ← Added so we can highlight "You"
            session['role'] = user['role']
            return redirect(url_for('dashboard'))
        else:
            return "Invalid credentials"
    try:
        return render_template('login.html')
    except Exception as e:
        print("Template error:", str(e))
        return "<h2 style='color:red'>Template 'login.html' failed to load</h2><p>Error: " + str(e) + "</p>"

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/add_game', methods=['GET', 'POST'])
def add_game():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form['title']
        genre = request.form.get('genre')
        release_year = request.form.get('release_year')
        summary = request.form.get('summary')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO Games (title, genre, release_year, summary) VALUES (%s, %s, %s, %s)",
            (title, genre, release_year, summary)
        )
        game_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO User_Games (user_id, game_id) VALUES (%s, %s)",
            (session['user_id'], game_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('dashboard'))
    return render_template('add_game.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/library')
def library():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    search = request.args.get('search')
    status = request.args.get('status')
    genre = request.args.get('genre')
    favorites_only = request.args.get('favorites') == '1'
    games = get_user_library(
        session['user_id'],
        search_term=search,
        status_filter=status,
        genre_filter=genre,
        favorite_only=favorites_only
    )
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT genre FROM Games WHERE genre IS NOT NULL")
    all_genres = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return render_template('library.html', 
                           games=games, 
                           search=search, 
                           status=status, 
                           genre=genre,
                           favorites_only=favorites_only,
                           genres=all_genres)

@app.route('/challenges')
def challenges():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    active_challenges = [
        {"challenge_id": 1, "name": "100 Hours Challenge", "description": "Play 100 hours this month", "end_date": "2026-03-31", "reward_points": 200},
        {"challenge_id": 2, "name": "Complete 5 Games", "description": "Finish 5 games before end of month", "end_date": "2026-04-30", "reward_points": 150}
    ]
    return render_template('challenges.html', challenges=active_challenges)

# ==================== RESTORED ORIGINAL LEADERBOARD ====================
@app.route('/leaderboard')
def leaderboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    board = get_leaderboard()                    # real database query
    current_username = session.get('username')   # this makes "You" highlight work
    
    return render_template('leaderboard.html', 
                           leaderboard=board, 
                           current_username=current_username)

@app.route('/moderate_reviews')
def moderate_reviews():
    if 'user_id' not in session or session.get('role') != 'admin':
        return "Access Denied - Admin only", 403
    reviews = get_pending_reviews()
    return render_template('moderate_reviews.html', reviews=reviews)

@app.route('/moderate_review/<int:review_id>', methods=['POST'])
def moderate_review_action(review_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return "Access Denied", 403
    action = request.form.get('action')
    approve = action == 'approve'
    moderate_review(review_id, approve)
    return redirect(url_for('moderate_reviews'))

STEAM_API_KEY = "3F062E133929F151C765B85BC031ECC3"

@app.route('/connect_steam', methods=['GET', 'POST'])
def connect_steam():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        steam_id = request.form.get('steam_id')
        if not steam_id:
            return "Please enter a Steam ID", 400
        url = f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_API_KEY}&steamid={steam_id}&format=json&include_appinfo=1"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            if 'response' not in data or 'games' not in data['response']:
                return f"Steam API error: No games found or profile is private.", 400
            games = data['response']['games']
            conn = get_db_connection()
            cursor = conn.cursor()
            added_count = 0
            duplicate_count = 0
            for game in games:
                appid = game['appid']
                title = game.get('name', f"Game {appid}")
                cursor.execute("SELECT game_id FROM Games WHERE title = %s", (title,))
                existing_game = cursor.fetchone()
                if existing_game:
                    game_id = existing_game[0]
                else:
                    cursor.execute("INSERT INTO Games (title) VALUES (%s)", (title,))
                    game_id = cursor.lastrowid
                cursor.execute(
                    "INSERT IGNORE INTO User_Games (user_id, game_id, status) VALUES (%s, %s, 'planned')",
                    (session['user_id'], game_id)
                )
                if cursor.rowcount == 1:
                    added_count += 1
                else:
                    duplicate_count += 1
            conn.commit()
            cursor.close()
            conn.close()
            message = f"Imported {added_count} new games from Steam! ({duplicate_count} were already in your library.)"
            return message
        except Exception as e:
            return f"Error connecting to Steam API: {str(e)}", 500
    return render_template('connect_steam.html')

@app.route('/update_game/<int:user_game_id>', methods=['GET', 'POST'])
def update_game(user_game_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT ug.*, g.title, g.genre 
        FROM User_Games ug 
        JOIN Games g ON ug.game_id = g.game_id 
        WHERE ug.user_game_id = %s AND ug.user_id = %s
    """, (user_game_id, session['user_id']))
    game = cursor.fetchone()
    cursor.close()
    conn.close()
    if not game:
        return "Game not found", 404
    if request.method == 'POST':
        status = request.form.get('status')
        hours_played = request.form.get('hours_played')
        notes = request.form.get('notes')
        completion_date = request.form.get('completion_date') or None
        is_favorite = 1 if request.form.get('is_favorite') else 0
        hours_played = int(hours_played) if hours_played and hours_played.isdigit() else game.get('hours_played', 0)
        update_game_status(user_game_id, session['user_id'], status, hours_played, notes, completion_date, is_favorite)
        return redirect(url_for('library'))
    return render_template('update_game.html', game=game)

@app.route('/toggle_favorite/<int:user_game_id>', methods=['POST'])
def toggle_favorite_route(user_game_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    is_fav = request.form.get('is_favorite') == '1'
    toggle_favorite(user_game_id, session['user_id'], is_fav)
    return redirect(url_for('library'))

@app.route('/join_challenge/<int:challenge_id>', methods=['POST'])
def handle_join_challenge(challenge_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    try:
        join_challenge(session['user_id'], challenge_id)
        return redirect(url_for('challenges'))
    except Exception as e:
        return f"Error joining challenge: {str(e)}", 500

@app.route('/my_challenges')
def my_challenges():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.name, c.description, c.end_date, uc.progress, c.goal, c.reward_points
        FROM User_Challenges uc
        JOIN Challenges c ON uc.challenge_id = c.challenge_id
        WHERE uc.user_id = %s
    """, (session['user_id'],))
    joined = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('my_challenges.html', joined=joined)

@app.route('/write_review/<int:game_id>', methods=['GET', 'POST'])
def write_review(game_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT 1 FROM User_Games WHERE user_id = %s AND game_id = %s", (session['user_id'], game_id))
    owns_game = cursor.fetchone()
    cursor.close()
    conn.close()
    if not owns_game:
        return "You can only review games in your library.", 403
    if request.method == 'POST':
        review_text = request.form['review_text']
        score = request.form.get('score')
        if not score or not score.isdigit() or not 1 <= int(score) <= 10:
            return "Score must be between 1 and 10.", 400
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO Reviews (user_id, game_id, review_text, score, approved) VALUES (%s, %s, %s, %s, 0)",
            (session['user_id'], game_id, review_text, int(score))
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('library'))
    return render_template('write_review.html', game_id=game_id)

@app.route('/reviews/<int:game_id>')
def game_reviews(game_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT r.review_text, r.score, r.created_at, u.username
        FROM Reviews r
        JOIN Users u ON r.user_id = u.user_id
        WHERE r.game_id = %s AND r.approved = 1
        ORDER BY r.created_at DESC
    """, (game_id,))
    reviews = cursor.fetchall()
    cursor.execute("SELECT title FROM Games WHERE game_id = %s", (game_id,))
    game = cursor.fetchone()
    cursor.close()
    conn.close()
    if not game:
        return "Game not found", 404
    return render_template('reviews.html', reviews=reviews, game_title=game['title'], game_id=game_id)

@app.route('/recommendations')
def recommendations():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    recs = get_ai_recommendations(session['user_id'])
    return render_template('recommendations.html', recommendations=recs)

if __name__ == '__main__':
    app.run(debug=True)
