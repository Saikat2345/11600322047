from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, HttpUrl
from datetime import datetime, timedelta
import string, random, logging, sqlite3

app = FastAPI(title="URL Shortener Service")

# ------------------ Logging Middleware ------------------
logger = logging.getLogger("url_shortener")
logging.basicConfig(level=logging.INFO)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response


# ------------------ Database Setup ------------------
def init_db():
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS urls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shortcode TEXT UNIQUE,
        original_url TEXT,
        expires_at TEXT
    )
    """)
    conn.commit()
    conn.close()

init_db()


# ------------------ Pydantic Schema ------------------
class URLRequest(BaseModel):
    url: HttpUrl
    validity: int | None = None   # in minutes
    shortcode: str | None = None


# ------------------ Helper Functions ------------------
def generate_shortcode(length: int = 6):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))

def get_db():
    return sqlite3.connect("urls.db")


# ------------------ API Routes ------------------
@app.post("/shorten")
def shorten_url(data: URLRequest):
    conn = get_db()
    cursor = conn.cursor()

    # Expiry time (default 30 mins)
    minutes = data.validity if data.validity else 30
    expires_at = datetime.utcnow() + timedelta(minutes=minutes)

    # Custom shortcode or generate one
    shortcode = data.shortcode if data.shortcode else generate_shortcode()

    # Ensure shortcode is unique
    cursor.execute("SELECT id FROM urls WHERE shortcode = ?", (shortcode,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Shortcode already exists")

    # Insert into DB
    try:
        cursor.execute(
            "INSERT INTO urls (shortcode, original_url, expires_at) VALUES (?, ?, ?)",
            (shortcode, str(data.url), expires_at.isoformat())
        )
        conn.commit()
    except Exception:
        conn.close()
        raise HTTPException(status_code=500, detail="Database error")

    conn.close()
    return {
        "short_url": f"http://localhost:8000/{shortcode}",
        "expires_at": expires_at
    }


@app.get("/{shortcode}")
def redirect_url(shortcode: str, request: Request):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT original_url, expires_at FROM urls WHERE shortcode = ?", (shortcode,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Shortcode not found")

    original_url, expires_at = row
    if datetime.utcnow() > datetime.fromisoformat(expires_at):
        raise HTTPException(status_code=410, detail="Short URL expired")

    # If request comes from Swagger UI, return JSON instead of redirect
    if "swagger" in str(request.headers.get("user-agent", "")).lower():
        return JSONResponse({"redirect_to": original_url})

    return RedirectResponse(url=original_url)
