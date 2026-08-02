"""Check whether required production environment values are configured."""
import os
from urllib.parse import urlparse

checks = {
    "PUBLIC_BASE_URL uses HTTPS": os.getenv("PUBLIC_BASE_URL", "").startswith("https://") and "yourdomain" not in os.getenv("PUBLIC_BASE_URL", ""),
    "ADMIN_TOKEN is customized": bool(os.getenv("ADMIN_TOKEN")) and os.getenv("ADMIN_TOKEN") != "replace-with-a-long-random-secret",
    "STRIPE_SECRET_KEY configured": bool(os.getenv("STRIPE_SECRET_KEY")),
    "STRIPE_WEBHOOK_SECRET configured": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
    "SMTP email configured": all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")),
    "PHOTOGRAPHER_EMAIL configured": bool(os.getenv("PHOTOGRAPHER_EMAIL")),
    "Twilio SMS configured": bool(os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN") and (os.getenv("TWILIO_FROM_NUMBER") or os.getenv("TWILIO_MESSAGING_SERVICE_SID"))),
    "PHOTOGRAPHER_PHONE configured": bool(os.getenv("PHOTOGRAPHER_PHONE")),
}
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'MISSING'}: {name}")
print("\nPrivate HTTPS testing:", "READY" if checks["PUBLIC_BASE_URL uses HTTPS"] and checks["ADMIN_TOKEN is customized"] else "NOT READY")
print("Live Stripe sales:", "READY" if all(checks[k] for k in ("PUBLIC_BASE_URL uses HTTPS", "ADMIN_TOKEN is customized", "STRIPE_SECRET_KEY configured", "STRIPE_WEBHOOK_SECRET configured")) else "NOT READY")
