# ═══════════════════════════════════════════════
# server.py — Self Shelf eBook Library Backend
# ═══════════════════════════════════════════════
#
# Stack:
#   Flask      — HTTP server + routing
#   Flask-CORS — allow cross-origin requests
#   SQLite3    — built-in Python database
#   werkzeug   — secure file handling (bundled with Flask)
#
# File layout:
#   uploads/      → uploaded ebook files stored on disk
#   library.db    → SQLite database (created automatically)
#   index.html    → the frontend (served as a static file)
#
# Run:
#   pip install flask flask-cors
#   python server.py
#
# API base: http://localhost:3000/api
# ═══════════════════════════════════════════════

import os
import sqlite3
import random
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename

# ───────────────────────────────────────────────
# CONFIG
# ───────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
UPLOADS_DIR = BASE_DIR / "uploads"
DB_PATH     = BASE_DIR / "library.db"
PORT = int(os.environ.get("PORT", 3000))
ALLOWED_EXT = {".pdf", ".epub", ".mobi", ".txt"}

UPLOADS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
CORS(app)  # allow all origins (fine for local development)


# ───────────────────────────────────────────────
# DATABASE HELPERS
# SQLite3 is built into Python — no install needed.
# We use a simple get_db() helper that creates a new
# connection per request (thread-safe for development).
# ───────────────────────────────────────────────

def get_db():
    """Open a SQLite connection with dict-style row access."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables on first run."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS folders (
                id   TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS books (
                id            TEXT    PRIMARY KEY,
                title         TEXT    NOT NULL,
                author        TEXT    NOT NULL DEFAULT 'Unknown Author',
                folder_id     TEXT    REFERENCES folders(id) ON DELETE SET NULL,
                ext           TEXT    NOT NULL,
                size          TEXT    NOT NULL,
                color         TEXT    NOT NULL,
                binding_color TEXT    NOT NULL,
                emoji         TEXT    NOT NULL,
                filename      TEXT    NOT NULL,
                filepath      TEXT    NOT NULL,
                created_at    INTEGER NOT NULL
            );
        """)


# ───────────────────────────────────────────────
# UTILITY HELPERS  (mirrors the JS helpers)
# ───────────────────────────────────────────────

def format_size(n):
    if n < 1024:           return f"{n} B"
    if n < 1024 * 1024:    return f"{n // 1024} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def random_color():
    palettes = [
        ("#0a0820", "#1a1248"), ("#0c1a30", "#182e50"),
        ("#1a0a10", "#301520"), ("#0a1a10", "#122a1a"),
        ("#180a28", "#2a1045"), ("#0a1828", "#142840"),
        ("#1a1000", "#2e1e00"), ("#0a0818", "#18103a"),
        ("#081818", "#102828"),
    ]
    a, b = random.choice(palettes)
    return f"linear-gradient(160deg, {a} 0%, {b} 100%)"


def random_binding_color():
    return random.choice([
        "#1a0a30", "#0a1a30", "#300a0a", "#0a2010",
        "#10082a", "#0a1020", "#2a1400", "#081020",
    ])


def get_emoji(filename):
    ext = Path(filename).suffix.lower().lstrip(".")
    return {"pdf": "📕", "epub": "📗", "mobi": "📘", "txt": "📄"}.get(ext, "📚")


def allowed_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXT


def row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row) if row else None


# ═══════════════════════════════════════════════
# STATIC FILE SERVING
# Serve index.html from the project root when
# the browser visits http://localhost:3000/
# ═══════════════════════════════════════════════

@app.route("/")
def serve_index():
    return send_from_directory(str(BASE_DIR), "index.html")


# ═══════════════════════════════════════════════
# FOLDERS API
# ═══════════════════════════════════════════════

@app.route("/api/folders", methods=["GET"])
def get_folders():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name FROM folders ORDER BY name ASC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/folders", methods=["POST"])
def create_folder():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Folder name is required."}), 400

    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM folders WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        if exists:
            return jsonify({"error": "A folder with that name already exists."}), 409

        folder_id = f"folder_{int(time.time() * 1000)}"
        conn.execute(
            "INSERT INTO folders (id, name) VALUES (?, ?)", (folder_id, name)
        )
    return jsonify({"id": folder_id, "name": name}), 201


@app.route("/api/folders/<folder_id>", methods=["PATCH"])
def rename_folder(folder_id):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Folder name is required."}), 400

    with get_db() as conn:
        conflict = conn.execute(
            "SELECT id FROM folders WHERE LOWER(name) = LOWER(?) AND id != ?",
            (name, folder_id)
        ).fetchone()
        if conflict:
            return jsonify({"error": "A folder with that name already exists."}), 409

        result = conn.execute(
            "UPDATE folders SET name = ? WHERE id = ?", (name, folder_id)
        )
        if result.rowcount == 0:
            return jsonify({"error": "Folder not found."}), 404
    return jsonify({"id": folder_id, "name": name})


@app.route("/api/folders/<folder_id>", methods=["DELETE"])
def delete_folder(folder_id):
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM folders WHERE id = ?", (folder_id,)
        )
        if result.rowcount == 0:
            return jsonify({"error": "Folder not found."}), 404
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════
# BOOKS API
# ═══════════════════════════════════════════════

@app.route("/api/books", methods=["GET"])
def get_books():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                id,
                title,
                author,
                folder_id    AS folderId,
                ext,
                size,
                color,
                binding_color AS bindingColor,
                emoji,
                filename,
                created_at   AS createdAt
            FROM books
            ORDER BY created_at DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/books", methods=["POST"])
def upload_book():
    if "file" not in request.files:
        return jsonify({"error": "No file received."}), 400

    file = request.files["file"]
    if not file.filename or not allowed_file(file.filename):
        return jsonify({"error": "Only PDF, EPUB, MOBI, and TXT files are allowed."}), 400

    # Build a safe on-disk filename: book_<timestamp>.<ext>
    ext       = Path(file.filename).suffix.lower()          # e.g. ".pdf"
    ext_plain = ext.lstrip(".")                              # e.g. "pdf"
    safe_name = f"book_{int(time.time() * 1000)}{ext}"     # e.g. "book_1712345678901.pdf"
    dest      = UPLOADS_DIR / safe_name
    file.save(str(dest))

    # Derive a human-friendly title from the original filename
    title = Path(file.filename).stem.replace("-", " ").replace("_", " ")

    folder_id  = request.form.get("folderId") or None
    book_id    = f"book_{int(time.time() * 1000)}"
    created_at = int(time.time() * 1000)
    size       = format_size(dest.stat().st_size)
    color      = random_color()
    binding    = random_binding_color()
    emoji      = get_emoji(file.filename)

    with get_db() as conn:
        conn.execute("""
            INSERT INTO books
              (id, title, author, folder_id, ext, size, color, binding_color,
               emoji, filename, filepath, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            book_id, title, "Unknown Author", folder_id, ext_plain,
            size, color, binding, emoji, file.filename, safe_name, created_at
        ))

    return jsonify({
        "id": book_id, "title": title, "author": "Unknown Author",
        "folderId": folder_id, "ext": ext_plain, "size": size,
        "color": color, "bindingColor": binding, "emoji": emoji,
        "filename": file.filename, "createdAt": created_at,
    }), 201


@app.route("/api/books/<book_id>", methods=["PATCH"])
def update_book(book_id):
    data      = request.get_json(force=True)
    folder_id = data.get("folderId") or None

    with get_db() as conn:
        result = conn.execute(
            "UPDATE books SET folder_id = ? WHERE id = ?", (folder_id, book_id)
        )
        if result.rowcount == 0:
            return jsonify({"error": "Book not found."}), 404
    return jsonify({"ok": True, "id": book_id, "folderId": folder_id})


@app.route("/api/books/<book_id>/download", methods=["GET"])
def download_book(book_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT filename, filepath FROM books WHERE id = ?", (book_id,)
        ).fetchone()

    if not row:
        return jsonify({"error": "Book not found."}), 404

    full_path = UPLOADS_DIR / row["filepath"]
    if not full_path.exists():
        return jsonify({"error": "File missing from disk."}), 404

    # send_file streams the file; as_attachment triggers a Save dialog
    return send_file(
        str(full_path),
        as_attachment=True,
        download_name=row["filename"],
    )


@app.route("/api/books/<book_id>", methods=["DELETE"])
def delete_book(book_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT filepath FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Book not found."}), 404

        # 1. Delete the physical file
        full_path = UPLOADS_DIR / row["filepath"]
        if full_path.exists():
            full_path.unlink()

        # 2. Remove the database record
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    print()
    print("📚 Self Shelf is running!")
    print(f"    Local:  http://localhost:{PORT}")
    print(f"    API:    http://localhost:{PORT}/api")
    print()
    app.run(host="0.0.0.0", port=PORT, debug=False)
