from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import shutil
import smtplib
import ssl
import sqlite3
import threading
import uuid
from io import BytesIO
from pathlib import Path
from typing import Iterable
from email.message import EmailMessage

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
PHOTO_DIR = DATA_DIR / "photos"
SELFIE_DIR = DATA_DIR / "selfies"
VIDEO_DIR = DATA_DIR / "videos"
DB_PATH = DATA_DIR / "app.db"

# buffalo_sc contains only the lightweight detection and recognition models.
# It is much smaller than buffalo_l and is the safe default for low-memory hosting.
EMBEDDING_MODEL = (os.getenv("FACE_MODEL", "buffalo_sc").strip() or "buffalo_sc")
FACE_MODEL_ROOT = os.getenv("FACE_MODEL_ROOT", "~/.insightface").strip() or "~/.insightface"
FACE_DET_SIZE = max(128, int(os.getenv("FACE_DET_SIZE", "320")))
FACE_MAX_IMAGE_DIM = max(640, int(os.getenv("FACE_MAX_IMAGE_DIM", "2000")))
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.42"))
BRAND_NAME = "Marin Fotografía y Video"
BRAND_PHONE = "713-378-1730"
PRINT_PRICES_CENTS = {"8x10": 2500, "11x14": 4000, "13x19": 5500, "16x20": 7500, "20x24": 11000, "24x30": 15000, "24x36": 19000}
SHIPPING_CENTS = 1295
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = "".join(os.getenv("SMTP_PASSWORD", "").split())
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME or "orders@localhost").strip()
PHOTOGRAPHER_EMAIL = os.getenv("PHOTOGRAPHER_EMAIL", "").strip()
ZELLE_RECIPIENT = os.getenv("ZELLE_RECIPIENT", "713-378-1730").strip() or "713-378-1730"

for directory in (DATA_DIR, PHOTO_DIR, SELFIE_DIR, VIDEO_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FaceFind Photos", version="0.3.0")

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    return response


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "FaceFind Photos",
        "face_model": EMBEDDING_MODEL,
        "face_model_loaded": _face_app is not None,
        "persistent_data_configured": os.getenv("DATA_DIR", "").startswith("/var/data"),
    }
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")

_face_app = None
_face_app_lock = threading.Lock()


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                event_date TEXT,
                location TEXT,
                price_cents INTEGER NOT NULL DEFAULT 1500,
                consent_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                status TEXT NOT NULL,
                total_cents INTEGER NOT NULL,
                photo_ids_json TEXT NOT NULL,
                video_ids_json TEXT NOT NULL DEFAULT '[]',
                order_items_json TEXT NOT NULL DEFAULT '[]',
                shipping_json TEXT NOT NULL DEFAULT '{}',
                access_token TEXT NOT NULL DEFAULT '',
                deletion_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                title TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                price_cents INTEGER NOT NULL DEFAULT 7500,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(event_id) REFERENCES events(id)
            );

            CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                preview_name TEXT NOT NULL,
                embeddings_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(event_id) REFERENCES events(id)
            );
            CREATE TABLE IF NOT EXISTS search_sessions (
                token TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(event_id) REFERENCES events(id)
            );
            CREATE INDEX IF NOT EXISTS idx_search_sessions_expiry ON search_sessions(expires_at);
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(orders)").fetchall()}
        if "video_ids_json" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN video_ids_json TEXT NOT NULL DEFAULT '[]'")
        if "order_items_json" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN order_items_json TEXT NOT NULL DEFAULT '[]'")
        if "shipping_json" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN shipping_json TEXT NOT NULL DEFAULT '{}'")
        if "access_token" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN access_token TEXT NOT NULL DEFAULT ''")
        if "deletion_requested" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN deletion_requested INTEGER NOT NULL DEFAULT 0")
        rows = connection.execute("SELECT id FROM orders WHERE access_token = '' OR access_token IS NULL").fetchall()
        for row in rows:
            connection.execute("UPDATE orders SET access_token = ? WHERE id = ?", (uuid.uuid4().hex + uuid.uuid4().hex, row[0]))



@app.get("/readiness")
def readiness_check():
    checks = {
        "https_public_url": PUBLIC_BASE_URL.startswith("https://") and "yourdomain" not in PUBLIC_BASE_URL,
        "admin_protection": bool(ADMIN_TOKEN) and ADMIN_TOKEN != "replace-with-a-long-random-secret",
        "stripe_secret_key": bool(STRIPE_SECRET_KEY),
        "stripe_webhook_secret": bool(STRIPE_WEBHOOK_SECRET),
        "email_delivery": bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD and SMTP_FROM),
        "photographer_email": bool(PHOTOGRAPHER_EMAIL),
    }
    required = ["https_public_url", "admin_protection"]
    commerce = ["stripe_secret_key", "stripe_webhook_secret"]
    ready_for_private_testing = all(checks[name] for name in required)
    ready_for_live_card_sales = ready_for_private_testing and all(checks[name] for name in commerce)
    return {
        "ok": True,
        "ready_for_private_testing": ready_for_private_testing,
        "ready_for_live_card_sales": ready_for_live_card_sales,
        "checks": checks,
        "note": "Email is recommended but not required for private testing.",
    }

@app.on_event("startup")
def startup() -> None:
    init_db()




def require_admin(request: Request) -> None:
    """Protect administrator endpoints with the Render ADMIN_TOKEN."""
    if not ADMIN_TOKEN:
        raise HTTPException(503, "ADMIN_TOKEN is not configured on the server.")
    supplied = request.headers.get("x-admin-token", "").strip()
    if not secrets.compare_digest(supplied, ADMIN_TOKEN):
        raise HTTPException(401, "Administrator authorization required.")


def issue_search_token(event_id: str, lifetime_seconds: int = 1800) -> str:
    """Create a short-lived token that can display only this event's protected previews."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with db() as connection:
        connection.execute("DELETE FROM search_sessions WHERE expires_at < ?", (now,))
        connection.execute(
            "INSERT INTO search_sessions(token, event_id, expires_at) VALUES (?, ?, ?)",
            (token, event_id, now + lifetime_seconds),
        )
    return token


def validate_search_token(token: str, event_id: str) -> None:
    if not token:
        raise HTTPException(403, "A valid photo-search session is required.")
    now = int(time.time())
    with db() as connection:
        row = connection.execute(
            "SELECT event_id, expires_at FROM search_sessions WHERE token = ?",
            (token,),
        ).fetchone()
    if row is None or row["event_id"] != event_id or int(row["expires_at"]) < now:
        raise HTTPException(403, "This protected preview link has expired. Search the event again.")


def send_order_email(order_id: str, recipient: str, status: str, total_cents: int, access_token: str = "", payment_method: str = "") -> bool:
    """Send an order email and write SMTP failures to Render logs."""
    if not SMTP_HOST or not recipient:
        print(f"[email] skipped: SMTP_HOST or recipient is missing (recipient={recipient!r})", flush=True)
        return False

    released = status in {"paid", "processing_prints", "shipped", "completed"}
    subject_status = "Your photo is ready to download" if released else "Order received"
    availability = (
        "Your payment has been confirmed. Open your private order page below to download your purchased files.\n"
        if released
        else "Your order is waiting for payment confirmation. Downloads will appear after the photographer approves payment.\n"
    )
    zelle_instructions = ""
    if payment_method == "zelle" and not released:
        zelle_instructions = (
            f"\nZELLE PAYMENT INSTRUCTIONS\n"
            f"Send: ${total_cents / 100:.2f}\n"
            f"To: {ZELLE_RECIPIENT}\n"
            f"Memo: Order {order_id[:8].upper()}\n"
            f"Verify the recipient in your banking app before sending.\n"
            f"The photographer will release downloads after confirming the payment.\n"
        )

    msg = EmailMessage()
    msg["Subject"] = f"{subject_status} • Marin Fotografía y Video • {order_id[:8].upper()}"
    msg["From"] = SMTP_FROM
    msg["To"] = recipient
    portal_line = f"Private order page: {PUBLIC_BASE_URL}/account/{access_token}\n\n" if access_token else ""
    msg.set_content(
        f"Thank you for your order.\n\n"
        f"Order: {order_id[:8].upper()}\n"
        f"Status: {status.replace('_', ' ')}\n"
        f"Total: ${total_cents / 100:.2f}\n\n"
        f"{availability}"
        f"{zelle_instructions}\n"
        f"{portal_line}"
        f"Marin Fotografía y Video • {BRAND_PHONE}"
    )

    context = ssl.create_default_context()
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20, context=context) as server:
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        print(f"[email] sent to {recipient} for order {order_id[:8].upper()} status={status}", flush=True)
        return True
    except Exception as exc:
        print(
            f"[email] failed for {recipient}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return False


def serialize_order(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "payment_method": row["payment_method"],
        "status": row["status"],
        "total_cents": row["total_cents"],
        "photo_ids": json.loads(row["photo_ids_json"] or "[]"),
        "video_ids": json.loads(row["video_ids_json"] or "[]"),
        "items": json.loads(row["order_items_json"] or "[]"),
        "shipping": json.loads(row["shipping_json"] or "{}"),
        "access_token": row["access_token"] if "access_token" in row.keys() else "",
        "deletion_requested": bool(row["deletion_requested"]) if "deletion_requested" in row.keys() else False,
        "created_at": row["created_at"],
    }


def get_face_app():
    """Load one CPU face model instance lazily and safely.

    The model is not loaded during normal page requests. Restricting InsightFace
    to detection + recognition avoids loading unused age and landmark networks.
    """
    global _face_app
    if _face_app is not None:
        return _face_app

    with _face_app_lock:
        if _face_app is not None:
            return _face_app

        try:
            import onnxruntime as ort
            from insightface.app import FaceAnalysis
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "InsightFace is not installed correctly. Run pip install -r requirements.txt."
            ) from exc

        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = 1
        session_options.inter_op_num_threads = 1
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        providers = ["CPUExecutionProvider"]
        face_app = FaceAnalysis(
            name=EMBEDDING_MODEL,
            root=FACE_MODEL_ROOT,
            allowed_modules=["detection", "recognition"],
            providers=providers,
            sess_options=session_options,
        )
        face_app.prepare(ctx_id=-1, det_size=(FACE_DET_SIZE, FACE_DET_SIZE))
        _face_app = face_app
        return _face_app


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def _load_face_image(image_path: Path) -> np.ndarray:
    """Decode a bounded-size BGR image to avoid large-photo memory spikes."""
    import cv2

    try:
        with Image.open(image_path) as source:
            # JPEG decoders can use a lower-resolution draft before full decoding.
            source.draft("RGB", (FACE_MAX_IMAGE_DIM, FACE_MAX_IMAGE_DIM))
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail(
                (FACE_MAX_IMAGE_DIM, FACE_MAX_IMAGE_DIM),
                Image.Resampling.LANCZOS,
            )
            rgb = np.asarray(image, dtype=np.uint8)
    except Exception as exc:
        raise HTTPException(400, f"Could not read image: {image_path.name}") from exc

    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def extract_embeddings(image_path: Path) -> list[list[float]]:
    image = _load_face_image(image_path)

    try:
        faces = get_face_app().get(image)
    except Exception as exc:
        raise HTTPException(
            503,
            "The face model is unavailable. Check the Render logs and model files.",
        ) from exc

    embeddings: list[list[float]] = []
    for face in faces:
        embedding = getattr(face, "normed_embedding", None)
        if embedding is None:
            embedding = normalize(np.asarray(face.embedding, dtype=np.float32))
        embeddings.append(np.asarray(embedding, dtype=np.float32).tolist())
    return embeddings


def safe_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


def make_watermarked_preview(source: Path, destination: Path) -> None:
    """Create a low-resolution, strongly watermarked preview that preserves the full frame."""
    with Image.open(source) as source_image:
        image = ImageOps.exif_transpose(source_image).convert("RGB")
        image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)

    canvas = image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    short_side = max(1, min(image.width, image.height))
    large_size = max(34, min(76, round(short_side * 0.07)))
    small_size = max(18, min(38, round(short_side * 0.033)))
    brand = "MARIN FOTOGRAFÍA Y VIDEO"
    notice = "VISTA PREVIA • COMPRA PARA DESCARGAR"

    def fitted_font(text: str, start_size: int, max_width: int, bold: bool = True):
        size = start_size
        while size > 16:
            font = _brand_font(size, bold=bold)
            box = draw.textbbox((0, 0), text, font=font)
            if box[2] - box[0] <= max_width:
                return font, size
            size -= 2
        return _brand_font(16, bold=bold), 16

    large_font, large_size = fitted_font(brand, large_size, round(image.width * 0.82))
    small_font, small_size = fitted_font(notice, small_size, round(image.width * 0.82))
    repeat_font, _ = fitted_font(brand, max(18, round(small_size * 0.9)), max(240, round(image.width * 0.45)))

    # Repeated marks make screenshots and browser sharing unsuitable as finished files.
    spacing_x = max(330, round(image.width * 0.48))
    spacing_y = max(190, round(image.height * 0.25))
    for row, y in enumerate(range(-spacing_y, image.height + spacing_y, spacing_y)):
        offset = -(spacing_x // 2) if row % 2 else 0
        for x in range(offset, image.width + spacing_x, spacing_x):
            draw.text((x + 2, y + 2), brand, font=repeat_font, fill=(0, 0, 0, 100), anchor="mm")
            draw.text((x, y), brand, font=repeat_font, fill=(255, 255, 255, 130), anchor="mm")

    # Large central protection mark.
    cx, cy = image.width // 2, image.height // 2
    brand_box = draw.textbbox((0, 0), brand, font=large_font)
    notice_box = draw.textbbox((0, 0), notice, font=small_font)
    panel_w = max(brand_box[2] - brand_box[0], notice_box[2] - notice_box[0]) + 64
    panel_h = (brand_box[3] - brand_box[1]) + (notice_box[3] - notice_box[1]) + 42
    draw.rounded_rectangle(
        (cx - panel_w // 2, cy - panel_h // 2, cx + panel_w // 2, cy + panel_h // 2),
        radius=max(14, round(short_side * 0.018)),
        fill=(5, 5, 8, 145),
        outline=(255, 255, 255, 105),
        width=max(1, round(short_side * 0.003)),
    )
    draw.text((cx + 3, cy - 12 + 3), brand, font=large_font, fill=(0, 0, 0, 180), anchor="mm")
    draw.text((cx, cy - 12), brand, font=large_font, fill=(255, 255, 255, 235), anchor="mm")
    draw.text((cx, cy + large_size * 0.68), notice, font=small_font, fill=(238, 214, 166, 235), anchor="mm")

    result = Image.alpha_composite(canvas, overlay).convert("RGB")
    result.save(destination, format="JPEG", quality=80, optimize=True)

def _brand_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default(size=max(10, size))


def add_brand_signature(source: Path, destination: Path, max_dimension: int | None = None) -> None:
    """Create the purchased JPEG without allocating full-size RGBA overlays.

    Large camera photographs can exceed Render memory when converted into several
    simultaneous RGBA copies. This implementation keeps one RGB image in memory
    and draws a small opaque brand panel directly onto it.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as source_image:
        image = ImageOps.exif_transpose(source_image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        else:
            image = image.copy()

    if max_dimension:
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    draw = ImageDraw.Draw(image)
    scale = max(1.0, min(image.width, image.height) / 1200)
    name_size = max(18, round(25 * scale))
    phone_size = max(15, round(19 * scale))
    name_font = _brand_font(name_size, bold=True)
    phone_font = _brand_font(phone_size)
    padding_x = max(18, round(24 * scale))
    padding_y = max(14, round(17 * scale))
    line_gap = max(3, round(4 * scale))
    outer_margin = max(20, round(28 * scale))

    name_box = draw.textbbox((0, 0), BRAND_NAME, font=name_font)
    phone_box = draw.textbbox((0, 0), BRAND_PHONE, font=phone_font)
    name_w, name_h = name_box[2] - name_box[0], name_box[3] - name_box[1]
    phone_w, phone_h = phone_box[2] - phone_box[0], phone_box[3] - phone_box[1]
    panel_w = max(name_w, phone_w) + padding_x * 2
    panel_h = name_h + phone_h + line_gap + padding_y * 2
    x2 = image.width - outer_margin
    y2 = image.height - outer_margin
    x1 = max(outer_margin, x2 - panel_w)
    y1 = max(outer_margin, y2 - panel_h)
    radius = max(10, round(14 * scale))

    draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=(16, 18, 24))
    text_x = x2 - padding_x
    name_y = y1 + padding_y
    phone_y = name_y + name_h + line_gap
    shadow = max(1, round(scale))
    draw.text((text_x + shadow, name_y + shadow), BRAND_NAME, font=name_font, anchor="ra", fill=(0, 0, 0))
    draw.text((text_x + shadow, phone_y + shadow), BRAND_PHONE, font=phone_font, anchor="ra", fill=(0, 0, 0))
    draw.text((text_x, name_y), BRAND_NAME, font=name_font, anchor="ra", fill=(255, 255, 255))
    draw.text((text_x, phone_y), BRAND_PHONE, font=phone_font, anchor="ra", fill=(232, 236, 240))

    # optimize=True can require substantial extra memory for large JPEGs.
    image.save(destination, format="JPEG", quality=94, subsampling=0, optimize=False)
    image.close()


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    av = normalize(np.asarray(list(a), dtype=np.float32))
    bv = normalize(np.asarray(list(b), dtype=np.float32))
    return float(np.dot(av, bv))




@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request, "brand_name": BRAND_NAME, "brand_phone": BRAND_PHONE})


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request, "brand_name": BRAND_NAME, "brand_phone": BRAND_PHONE})


@app.get("/biometric-consent", response_class=HTMLResponse)
def biometric_consent_page(request: Request):
    return templates.TemplateResponse("biometric_consent.html", {"request": request, "brand_name": BRAND_NAME, "brand_phone": BRAND_PHONE})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "event_id": "", "zelle_recipient": ZELLE_RECIPIENT})


@app.get("/invitations/demo/{theme}", response_class=HTMLResponse)
def invitation_demo(request: Request, theme: str):
    demos = {
        "rose-gold": {"theme": "rose-gold", "name": "Sofia", "date": "NOVEMBER 21, 2026", "title": "Mis XV Años", "subtitle": "A rose-gold scrolling invitation"},
        "royal-blue": {"theme": "royal-blue", "name": "Isabella", "date": "DECEMBER 5, 2026", "title": "Quinceañera", "subtitle": "A royal blue and silver invitation"},
        "emerald": {"theme": "emerald", "name": "Valentina", "date": "JANUARY 16, 2027", "title": "Celebración de XV", "subtitle": "An emerald and champagne invitation"},
    }
    demo = demos.get(theme)
    if demo is None:
        raise HTTPException(404, "Invitation demo not found.")
    return templates.TemplateResponse("invitation_demo.html", {"request": request, **demo})


@app.get("/e/{event_id}", response_class=HTMLResponse)
def event_landing(request: Request, event_id: str):
    with db() as connection:
        event = connection.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        raise HTTPException(404, "Event not found.")
    return templates.TemplateResponse("index.html", {"request": request, "event_id": event_id, "zelle_recipient": ZELLE_RECIPIENT})


@app.get("/account/{access_token}", response_class=HTMLResponse)
def customer_account(request: Request, access_token: str):
    with db() as connection:
        row = connection.execute("SELECT * FROM orders WHERE access_token = ?", (access_token,)).fetchone()
    if row is None:
        raise HTTPException(404, "Private order page not found.")
    order = serialize_order(row)
    return templates.TemplateResponse("account.html", {"request": request, "order": order, "brand_phone": BRAND_PHONE, "zelle_recipient": ZELLE_RECIPIENT})


@app.get("/api/customer/orders/{access_token}")
def customer_order(access_token: str):
    with db() as connection:
        row = connection.execute("SELECT * FROM orders WHERE access_token = ?", (access_token,)).fetchone()
    if row is None:
        raise HTTPException(404, "Order not found.")
    order = serialize_order(row)
    order.pop("access_token", None)
    return {"order": order}


@app.post("/api/customer/orders/{access_token}/request-deletion")
def request_customer_deletion(access_token: str):
    with db() as connection:
        row = connection.execute("SELECT id FROM orders WHERE access_token = ?", (access_token,)).fetchone()
        if row is None:
            raise HTTPException(404, "Order not found.")
        connection.execute("UPDATE orders SET deletion_requested = 1 WHERE access_token = ?", (access_token,))
    return {"ok": True, "message": "Your privacy request was recorded. The photographer will review it before deleting records required for payments, taxes, or fulfillment."}


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(BASE_DIR / "app" / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/api/events")
def list_events():
    with db() as connection:
        rows = connection.execute(
            """
            SELECT e.*, COUNT(p.id) AS photo_count
            FROM events e
            LEFT JOIN photos p ON p.event_id = e.id
            GROUP BY e.id
            ORDER BY e.created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/events")
def create_event(
    name: str = Form(...),
    event_date: str = Form(""),
    location: str = Form(""),
    price: float = Form(15.0),
    consent_text: str = Form(...),
):
    if not consent_text.strip():
        raise HTTPException(400, "Consent text is required.")
    event_id = uuid.uuid4().hex
    price_cents = max(0, int(round(price * 100)))
    with db() as connection:
        connection.execute(
            "INSERT INTO events(id, name, event_date, location, price_cents, consent_text) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, name.strip(), event_date.strip(), location.strip(), price_cents, consent_text.strip()),
        )
    return {"id": event_id, "ok": True}


@app.get("/api/events/{event_id}/qr")
def event_qr(event_id: str, request: Request):
    with db() as connection:
        event = connection.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        raise HTTPException(404, "Event not found.")

    import qrcode

    event_url = str(request.base_url).rstrip("/") + f"/e/{event_id}"
    qr = qrcode.QRCode(version=None, box_size=10, border=4)
    qr.add_data(event_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="event-{event_id}-qr.png"'},
    )


@app.post("/api/events/{event_id}/photos")
async def upload_photos(event_id: str, files: list[UploadFile] = File(...)):
    with db() as connection:
        event = connection.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        raise HTTPException(404, "Event not found.")

    uploaded = []
    for upload in files:
        suffix = safe_suffix(upload.filename or "photo.jpg")
        photo_id = uuid.uuid4().hex
        stored_name = f"{photo_id}{suffix}"
        preview_name = f"{photo_id}_preview.jpg"
        stored_path = PHOTO_DIR / stored_name
        preview_path = PHOTO_DIR / preview_name

        with stored_path.open("wb") as output:
            shutil.copyfileobj(upload.file, output)

        try:
            embeddings = extract_embeddings(stored_path)
            make_watermarked_preview(stored_path, preview_path)
        except Exception:
            stored_path.unlink(missing_ok=True)
            preview_path.unlink(missing_ok=True)
            raise

        with db() as connection:
            connection.execute(
                """
                INSERT INTO photos(id, event_id, original_name, stored_name, preview_name, embeddings_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    photo_id,
                    event_id,
                    upload.filename or stored_name,
                    stored_name,
                    preview_name,
                    json.dumps(embeddings),
                ),
            )
        uploaded.append({"id": photo_id, "faces": len(embeddings), "name": upload.filename})

    return {"uploaded": uploaded}


@app.post("/api/events/{event_id}/videos")
async def upload_event_video(
    event_id: str,
    title: str = Form("Video del baile"),
    price: float = Form(75.0),
    video: UploadFile = File(...),
):
    with db() as connection:
        event = connection.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        raise HTTPException(404, "Event not found.")
    suffix = Path(video.filename or "dance-video.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".m4v", ".webm"}:
        raise HTTPException(400, "Upload MP4, MOV, M4V, or WebM video.")
    video_id = uuid.uuid4().hex
    stored_name = f"{video_id}{suffix}"
    with (VIDEO_DIR / stored_name).open("wb") as output:
        shutil.copyfileobj(video.file, output)
    price_cents = max(0, int(round(price * 100)))
    with db() as connection:
        connection.execute(
            "INSERT INTO videos(id, event_id, title, stored_name, price_cents) VALUES (?, ?, ?, ?, ?)",
            (video_id, event_id, title.strip() or "Video del baile", stored_name, price_cents),
        )
    return {"ok": True, "id": video_id, "title": title, "price_cents": price_cents}


@app.post("/api/search")
async def search_faces(
    event_id: str = Form(...),
    consent: bool = Form(...),
    selfie: UploadFile = File(...),
):
    if not consent:
        raise HTTPException(400, "Consent is required before biometric search.")

    suffix = safe_suffix(selfie.filename or "selfie.jpg")
    selfie_name = f"{uuid.uuid4().hex}{suffix}"
    selfie_path = SELFIE_DIR / selfie_name
    with selfie_path.open("wb") as output:
        shutil.copyfileobj(selfie.file, output)

    try:
        selfie_embeddings = extract_embeddings(selfie_path)
    finally:
        selfie_path.unlink(missing_ok=True)

    if not selfie_embeddings:
        raise HTTPException(400, "No face was detected in the selfie.")

    query_embedding = selfie_embeddings[0]
    matches = []
    with db() as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(404, "Event not found.")
        photos = connection.execute("SELECT * FROM photos WHERE event_id = ?", (event_id,)).fetchall()
        videos = connection.execute("SELECT id, title, price_cents FROM videos WHERE event_id = ? ORDER BY created_at", (event_id,)).fetchall()

    for photo in photos:
        embeddings = json.loads(photo["embeddings_json"])
        best_score = max((cosine_similarity(query_embedding, e) for e in embeddings), default=-1.0)
        if best_score >= MATCH_THRESHOLD:
            matches.append(
                {
                    "id": photo["id"],
                    "preview_url": f"/api/photos/{photo['id']}/preview",
                    "score": round(best_score, 4),
                    "price_cents": event["price_cents"],
                }
            )

    matches.sort(key=lambda item: item["score"], reverse=True)
    search_token = issue_search_token(event_id)
    for match in matches:
        match["preview_url"] = f"/api/photos/{match['id']}/preview?token={search_token}"
    protected_videos = []
    for video in videos:
        item = dict(video)
        item["preview_url"] = f"/api/videos/{item['id']}/preview?token={search_token}"
        protected_videos.append(item)
    return {
        "event": dict(event),
        "matches": matches,
        "videos": protected_videos,
        "search_token": search_token,
        "threshold": MATCH_THRESHOLD,
        "preview_expires_in": 1800,
    }


@app.get("/api/photos/{photo_id}/preview")
def photo_preview(photo_id: str, token: str = ""):
    with db() as connection:
        photo = connection.execute(
            "SELECT event_id, preview_name FROM photos WHERE id = ?",
            (photo_id,),
        ).fetchone()
    if photo is None:
        raise HTTPException(404, "Photo not found.")
    validate_search_token(token, photo["event_id"])
    return FileResponse(
        PHOTO_DIR / photo["preview_name"],
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "Content-Disposition": "inline",
        },
    )


@app.get("/api/photos/{photo_id}/signature-preview")
def photo_signature_preview(photo_id: str, request: Request):
    """Administrator-only sample of the final branded digital file."""
    require_admin(request)
    with db() as connection:
        photo = connection.execute("SELECT stored_name FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if photo is None:
        raise HTTPException(404, "Photo not found.")
    source = PHOTO_DIR / photo["stored_name"]
    output = PHOTO_DIR / f"{photo_id}_signature_preview.jpg"
    add_brand_signature(source, output, max_dimension=1600)
    return FileResponse(output, media_type="image/jpeg")


@app.get("/api/orders/{order_id}/photos/{photo_id}/download")
def download_purchased_digital(order_id: str, photo_id: str):
    """Release a full-resolution branded digital only after the order is marked paid."""
    with db() as connection:
        order = connection.execute("SELECT status, photo_ids_json FROM orders WHERE id = ?", (order_id,)).fetchone()
        photo = connection.execute("SELECT stored_name, original_name FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if order is None or photo is None:
        raise HTTPException(404, "Order or photo not found.")
    if order["status"] not in {"paid", "processing_prints", "shipped", "completed"}:
        raise HTTPException(403, "This download is released only after payment is confirmed.")
    purchased_ids = json.loads(order["photo_ids_json"])
    if photo_id not in purchased_ids:
        raise HTTPException(403, "This photo is not part of the order.")

    source = PHOTO_DIR / photo["stored_name"]
    output = PHOTO_DIR / f"{order_id}_{photo_id}_digital.jpg"
    if not source.is_file():
        print(f"[download] missing source file: {source}", flush=True)
        raise HTTPException(404, "The purchased photo file is missing. Contact the photographer.")
    if not output.is_file():
        try:
            add_brand_signature(source, output)
        except Exception as exc:
            print(
                f"[download] failed order={order_id[:8]} photo={photo_id[:8]}: {type(exc).__name__}: {exc}",
                flush=True,
            )
            output.unlink(missing_ok=True)
            raise HTTPException(503, "The download is being prepared. Please try again in a moment.") from exc
    safe_name = Path(photo["original_name"]).stem or "marin-photo"
    return FileResponse(
        output,
        media_type="image/jpeg",
        filename=f"{safe_name}-Marin-Fotografia-y-Video.jpg",
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )


@app.get("/api/videos/{video_id}/preview")
def video_preview(video_id: str, token: str = ""):
    with db() as connection:
        video = connection.execute(
            "SELECT event_id, stored_name FROM videos WHERE id = ?",
            (video_id,),
        ).fetchone()
    if video is None:
        raise HTTPException(404, "Video not found.")
    validate_search_token(token, video["event_id"])
    return FileResponse(
        VIDEO_DIR / video["stored_name"],
        media_type="video/mp4",
        headers={"Cache-Control": "private, no-store, max-age=0", "Content-Disposition": "inline"},
    )


@app.get("/api/orders/{order_id}/videos/{video_id}/download")
def download_purchased_video(order_id: str, video_id: str):
    with db() as connection:
        order = connection.execute("SELECT status, video_ids_json FROM orders WHERE id = ?", (order_id,)).fetchone()
        video = connection.execute("SELECT stored_name, title FROM videos WHERE id = ?", (video_id,)).fetchone()
    if order is None or video is None:
        raise HTTPException(404, "Order or video not found.")
    if order["status"] not in {"paid", "processing_prints", "shipped", "completed"}:
        raise HTTPException(403, "This video is released only after payment is confirmed.")
    if video_id not in json.loads(order["video_ids_json"] or "[]"):
        raise HTTPException(403, "This video is not part of the order.")
    filename = f"{video['title']}-Marin-Fotografia-y-Video{Path(video['stored_name']).suffix}"
    return FileResponse(VIDEO_DIR / video["stored_name"], filename=filename)


@app.get("/api/admin/orders")
def admin_orders(request: Request):
    require_admin(request)
    with db() as connection:
        rows = connection.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 250").fetchall()
    return {"orders": [serialize_order(row) for row in rows]}


@app.patch("/api/admin/orders/{order_id}")
def update_order_status(order_id: str, payload: dict, request: Request):
    require_admin(request)
    status = str(payload.get("status") or "").strip()
    allowed = {"demo_payment_pending", "pending_manual_payment", "paid", "processing_prints", "shipped", "completed", "cancelled", "refunded"}
    if status not in allowed:
        raise HTTPException(400, "Unsupported order status.")
    with db() as connection:
        row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Order not found.")
        connection.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    emailed = send_order_email(order_id, row["email"], status, row["total_cents"], row["access_token"], row["payment_method"])
    return {"ok": True, "order_id": order_id, "status": status, "email_sent": emailed}


@app.post("/api/admin/email-test")
def admin_email_test(payload: dict, request: Request):
    require_admin(request)
    recipient = str(payload.get("email") or PHOTOGRAPHER_EMAIL or SMTP_USERNAME).strip()
    if "@" not in recipient:
        raise HTTPException(400, "Enter a valid email address for the test.")
    sent = send_order_email("emailtest", recipient, "paid", 0, "")
    if not sent:
        raise HTTPException(502, "Email test failed. Open Render Logs and look for a line beginning with [email] failed.")
    return {"ok": True, "email_sent": True, "recipient": recipient}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, "Stripe webhook is not configured.")
    try:
        import stripe
    except Exception as exc:
        raise HTTPException(503, "Stripe package is not installed.") from exc
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        raise HTTPException(400, "Invalid Stripe webhook.") from exc
    if event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        order_id = (session.get("metadata") or {}).get("order_id")
        if order_id:
            with db() as connection:
                row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
                if row:
                    connection.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
            if row:
                send_order_email(order_id, row["email"], "paid", row["total_cents"], row["access_token"])
    return {"received": True}


@app.post("/api/checkout")
def checkout(payload: dict):
    photo_items = payload.get("photo_items") or []
    video_ids = list(dict.fromkeys(payload.get("video_ids") or []))
    payment_method = str(payload.get("payment_method") or "card").strip().lower()
    email = str(payload.get("email") or "").strip()
    shipping = payload.get("shipping") or {}
    allowed_methods = {"card", "apple_pay", "google_pay", "paypal", "cash", "zelle"}

    normalized_items = []
    for item in photo_items:
        photo_id = str(item.get("photo_id") or "")
        product = str(item.get("product") or "digital")
        quantity = max(1, min(20, int(item.get("quantity") or 1)))
        if not photo_id or (product != "digital" and product not in PRINT_PRICES_CENTS):
            raise HTTPException(400, "Invalid photo product selection.")
        normalized_items.append({"photo_id": photo_id, "product": product, "quantity": quantity})

    if not normalized_items and not video_ids:
        raise HTTPException(400, "Cart is empty.")
    if payment_method not in allowed_methods:
        raise HTTPException(400, "Unsupported payment method.")
    if "@" not in email or len(email) > 254:
        raise HTTPException(400, "A valid receipt email is required.")

    photo_ids = list(dict.fromkeys(item["photo_id"] for item in normalized_items))
    with db() as connection:
        photo_rows = []
        video_rows = []
        if photo_ids:
            placeholders = ",".join("?" for _ in photo_ids)
            photo_rows = connection.execute(
                f"SELECT p.id, e.price_cents FROM photos p JOIN events e ON e.id = p.event_id WHERE p.id IN ({placeholders})", tuple(photo_ids)
            ).fetchall()
        if video_ids:
            placeholders = ",".join("?" for _ in video_ids)
            video_rows = connection.execute(f"SELECT id, price_cents FROM videos WHERE id IN ({placeholders})", tuple(video_ids)).fetchall()

    if len(photo_rows) != len(photo_ids) or len(video_rows) != len(video_ids):
        raise HTTPException(400, "One or more selected items are unavailable.")
    photo_price = {row["id"]: row["price_cents"] for row in photo_rows}
    total = 0
    requires_shipping = False
    for item in normalized_items:
        unit = photo_price[item["photo_id"]] if item["product"] == "digital" else PRINT_PRICES_CENTS[item["product"]]
        item["unit_price_cents"] = unit
        total += unit * item["quantity"]
        requires_shipping = requires_shipping or item["product"] != "digital"
    total += sum(row["price_cents"] for row in video_rows)

    if requires_shipping:
        required = ["name", "address", "city", "state", "postal_code", "country"]
        if any(not str(shipping.get(field) or "").strip() for field in required):
            raise HTTPException(400, "Complete the shipping address for printed products.")
        total += SHIPPING_CENTS
    else:
        shipping = {}

    order_id = uuid.uuid4().hex
    access_token = uuid.uuid4().hex + uuid.uuid4().hex
    manual = payment_method in {"cash", "zelle"}
    status = "pending_manual_payment" if manual else "demo_payment_pending"
    digital_photo_ids = [item["photo_id"] for item in normalized_items if item["product"] == "digital"]
    with db() as connection:
        connection.execute(
            "INSERT INTO orders(id, email, payment_method, status, total_cents, photo_ids_json, video_ids_json, order_items_json, shipping_json, access_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, email, payment_method, status, total, json.dumps(digital_photo_ids), json.dumps(video_ids), json.dumps(normalized_items), json.dumps(shipping), access_token),
        )

    provider_names = {"card":"Stripe card checkout","apple_pay":"Apple Pay through Stripe","google_pay":"Google Pay through Stripe","paypal":"PayPal Checkout","cash":"cash payment","zelle":"Zelle/manual transfer"}
    redirect_url = None
    mode = "demo"
    if payment_method in {"card", "apple_pay", "google_pay"} and STRIPE_SECRET_KEY:
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            session = stripe.checkout.Session.create(
                mode="payment",
                customer_email=email,
                line_items=[{"price_data":{"currency":"usd","product_data":{"name":f"Marin photo/video order {order_id[:8].upper()}"},"unit_amount":total},"quantity":1}],
                success_url=f"{PUBLIC_BASE_URL}/account/{access_token}?payment=success",
                cancel_url=f"{PUBLIC_BASE_URL}/account/{access_token}?payment=cancelled",
                metadata={"order_id": order_id},
            )
            redirect_url = session.url
            mode = "live"
            message = "Secure Stripe checkout is ready."
        except Exception:
            message = "The order was saved, but Stripe could not create a checkout session. Verify the merchant configuration."
    elif manual:
        message = f"Order saved for {provider_names[payment_method]}. The photographer must verify payment before downloads are released."
    else:
        message = f"Demo order created for {provider_names[payment_method]}. Connect merchant credentials to charge the customer."

    emailed = send_order_email(order_id, email, status, total, access_token, payment_method)
    if PHOTOGRAPHER_EMAIL:
        send_order_email(order_id, PHOTOGRAPHER_EMAIL, status, total, access_token, payment_method)
    zelle_payment = None
    if payment_method == "zelle":
        zelle_payment = {
            "recipient": ZELLE_RECIPIENT,
            "amount_cents": total,
            "memo": f"Order {order_id[:8].upper()}",
        }
    return JSONResponse({"ok":True,"mode":mode,"order_id":order_id,"payment_method":payment_method,"status":status,"message":message,"items":len(normalized_items)+len(video_rows),"total_cents":total,"shipping_cents":SHIPPING_CENTS if requires_shipping else 0,"redirect_url":redirect_url,"email_sent":emailed,"customer_portal_url":f"{PUBLIC_BASE_URL}/account/{access_token}","zelle_payment":zelle_payment})
