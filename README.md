# Marin Fotografía y Video — FaceFind Photos MVP

A mobile-friendly, installable web app for consent-based face matching in event photography.

## GitHub y Render

Para subir este proyecto, consulta `GITHUB_UPLOAD.md`. Todos los archivos principales deben permanecer en la raíz del repositorio.

## What works

- Create photography events
- Upload multiple event photos
- Detect and index every face using InsightFace embeddings
- Customer selfie upload with explicit consent
- One-event-only face matching
- Selfie deletion immediately after matching
- Watermarked result previews
- Shopping cart and demo checkout total
- PWA installation shell for iPhone/Android
- Unique QR code and guest web page for every event
- QR scan opens the correct event automatically


## Render memory and persistence fix

See `RENDER_MEMORY_FIX.md` before redeploying. This package uses a compact face model, limits CPU-library threads, reduces large images before inference, and stores runtime data under the configurable `DATA_DIR`. On Render, attach a persistent disk at `/var/data` so events, SQLite data, uploaded photos, and videos survive restarts.

## Privacy design

- Search is limited to one selected event.
- The customer's selfie is deleted after processing.
- The app stores mathematical face embeddings for event photos, so event consent and a retention policy are required.
- Do not use this project for surveillance, covert identification, or searching unrelated public databases.

## Run locally

Python 3.11 is recommended.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

The Docker image downloads the compact `buffalo_sc` model during the build, so the running Render service does not download and unzip a large model during a customer request. Local non-Docker runs may download the configured model on first use. CPU matching works for an MVP, but large galleries should use background processing and a vector database.

## Environment settings

```bash
export MATCH_THRESHOLD=0.42
export FACE_MODEL=buffalo_sc
```

A higher threshold reduces false positives but may miss more photos. Test with your own event conditions before production use.

## Production upgrades still required

1. User login and photographer accounts
2. Cloud object storage (Amazon S3, Cloudflare R2, or Supabase Storage)
3. PostgreSQL plus pgvector, Qdrant, or another vector index
4. Background photo processing queue
5. Stripe Checkout and paid-download authorization
6. Signed URLs for original files
7. Event consent records, age/guardian workflows, deletion requests, and retention controls
8. Rate limiting, audit logs, encryption, backups, and abuse monitoring
9. Native iOS/Android wrapper or App Store build if desired

## Suggested business model

- Photographer subscription
- Per-event processing fee
- Percentage of photo sales
- White-label plan


## QR guest workflow

1. Create an event in the photographer dashboard.
2. Click **Download QR** beside that event.
3. Print the QR on a sign, card, table display, or event screen.
4. A guest scans it and opens `/e/EVENT_ID`.
5. The event is selected automatically; the guest uploads a selfie and sees only matches from that event.

The QR must use the public HTTPS address of the deployed app. A QR generated while running at `127.0.0.1` will only work on that same computer.

## Payment methods included in this version

The customer checkout now offers:

- Credit/debit cards
- Apple Pay
- Google Pay
- PayPal
- Cash at the event
- Zelle/manual bank transfer

The MVP creates and stores an order with its chosen payment method and total. It intentionally runs in **demo mode** and does not charge real money.

For production payments, connect:

- **Stripe Checkout or Payment Element** for cards, Apple Pay, and Google Pay
- **PayPal Checkout** for PayPal
- A photographer approval screen for cash and Zelle/manual transfers

Apple Pay and Google Pay require a public HTTPS domain and merchant configuration. Never place secret API keys in the browser; keep them in server environment variables.


## Invitation sharing and ordering

Each Marin Luxury Invitations demo now includes a fixed **Share** button that opens the phone's native share sheet. On browsers without native sharing, the app copies the demo URL to the clipboard. Each demo also includes **Order this design**, which returns the customer to the homepage and automatically selects Marin Luxury Invitations in the inquiry form with the chosen design identified.

## Branded digital downloads

Paid digital images are generated automatically in full resolution with a discreet modern signature in the lower-right corner:

- Marin Fotografía y Video
- 713-378-1730

The signature scales to the image resolution and uses a subtle translucent background for readability without covering important content.

### Endpoints

- `GET /api/photos/{photo_id}/signature-preview` — reduced-resolution branding preview.
- `GET /api/orders/{order_id}/photos/{photo_id}/download` — full-resolution customer download. The order must have status `paid`, and the photo must belong to that order.

The present MVP still uses demo payments. Once Stripe or PayPal webhooks are connected, successful payment should change the order status to `paid`, which unlocks the download endpoint.

## QR camera and facial-search guest flow

Each event QR opens `/e/{event_id}` and locks the guest to that event. The page now asks for one-time consent, opens the front camera through `getUserMedia`, captures a selfie, shows a preview, and submits it to `/api/search`. The server deletes the temporary selfie after generating the facial embedding and returns matching watermarked event photos.

Camera access requires a public HTTPS address (localhost is accepted for local development). Browsers require a guest tap before camera access, so the page uses an explicit **Open camera and take selfie** button.


## Dance video sales
The photographer dashboard now supports uploading a full dance video for each event, setting its title and price, and offering it beside matched photos. Customers can preview the event video, add it to the same cart, choose any supported payment method, and receive the protected download only after payment is marked paid.

## Update: digital downloads and professional prints

Each matched photo now offers a product selector for:

- Branded high-resolution digital download
- 8x10 print
- 11x14 print
- 13x19 print
- 16x20 print
- 20x24 print
- 24x30 print
- 24x36 print

The checkout stores the selected product for each photo. If any physical print is selected, the customer must provide a shipping address and the demo adds a flat $12.95 shipping fee. Print prices are configured in `PRINT_PRICES_CENTS` inside `app/main.py` and can be changed before launch.

## Production checkout, email, and order management update

This version adds an administrator order queue and optional production integrations.

### Admin order workflow

- Open **Photographer dashboard → Orders**.
- Review customer email, products, videos, shipping address, payment method, and total.
- Change an order to `paid` to release protected digital and video downloads.
- Continue with `processing_prints`, `shipped`, and `completed` for physical orders.
- Set `ADMIN_TOKEN` in production and enter that token in the dashboard before loading orders.

### Stripe

Install dependencies and configure:

```bash
export PUBLIC_BASE_URL=https://your-domain.com
export STRIPE_SECRET_KEY=sk_live_...
export STRIPE_WEBHOOK_SECRET=whsec_...
```

Cards, Apple Pay, and Google Pay use Stripe Checkout when `STRIPE_SECRET_KEY` is present. Configure the webhook endpoint as:

```text
https://your-domain.com/api/stripe/webhook
```

A successful `checkout.session.completed` webhook marks the order `paid` and releases protected downloads.

### Email confirmations

Configure an SMTP account:

```bash
export SMTP_HOST=smtp.example.com
export SMTP_PORT=587
export SMTP_USERNAME=orders@example.com
export SMTP_PASSWORD=your-app-password
export SMTP_FROM=orders@example.com
export PHOTOGRAPHER_EMAIL=your-business@example.com
```

The app then emails the customer when an order is created or its status changes. It can also send a copy to the photographer.

PayPal remains a prepared checkout option but still requires a PayPal Business integration before it can charge customers.

## Private customer order portal

Each checkout now creates a cryptographically random private link. Customers can use it to:

- check order and fulfillment status;
- return later to download paid digital photos and purchased video;
- review shipping information;
- submit a privacy/data-deletion request.

The private portal URL is returned by the checkout API and included in confirmation emails when SMTP is configured. Do not expose or log these links publicly. Production deployments should use HTTPS, secure backups, a strong `ADMIN_TOKEN`, and a formal retention/deletion policy.

## Launch privacy and legal pages

This version adds `/privacy`, `/terms`, and `/biometric-consent`, plus footer links throughout the main page. These are launch-preparation drafts and must be reviewed by a qualified attorney before public use, especially because biometric privacy laws differ by jurisdiction.

## Production deployment checklist

- Publish only behind HTTPS.
- Set a strong `ADMIN_TOKEN` and keep secrets outside source control.
- Configure a production database and private object storage.
- Connect Stripe/PayPal webhooks and verify signatures.
- Configure SMTP with a business sender domain.
- Add backups, monitoring, logs, rate limits, and malware scanning.
- Confirm selfie deletion and facial-template retention behavior with automated tests.
- Obtain event-organizer/parental permissions where minors are photographed.
- Finalize refund, shipping, copyright-license, and retention policies.

## Deployment-ready update

This package now includes:

- `Dockerfile` and `.dockerignore`
- `.env.example` for secrets and production settings
- `render.yaml` for an HTTPS web-service deployment
- `GET /health` monitoring endpoint
- `DEPLOYMENT.md` with testing and launch instructions

This configuration is suitable for a controlled MVP test. Production biometric search still requires a managed database, private object storage, hardened authentication, monitoring, legal review, and jurisdiction-specific consent controls.

## Professional protected-gallery update

See `PRO_SECURITY_UPDATE.md`. This revision adds explicit photo cart buttons, uncropped portrait previews, larger watermarks, short-lived preview authorization, paid-only original downloads, and a network-first service worker so new designs are not hidden by an old browser cache.
