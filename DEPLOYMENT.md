# Publicación segura

## Opción recomendada para probar

1. Crea un repositorio privado en GitHub y sube este proyecto.
2. En Render, crea un servicio web usando el archivo `render.yaml`.
3. Define `PUBLIC_BASE_URL` con la URL HTTPS pública.
4. Define las claves privadas únicamente en el panel del proveedor.
5. Abre `/health` para confirmar que el servicio responde.
6. Crea un evento y descarga un QR nuevo; los QR anteriores de localhost no sirven públicamente.
7. Prueba cámara y selfie desde Safari en iPhone y Chrome en Android.

## Antes de aceptar clientes reales

- Cambia SQLite por PostgreSQL.
- Guarda originales y videos en almacenamiento privado S3/R2.
- Usa URLs firmadas para descargas.
- Verifica webhooks de Stripe y PayPal.
- Configura copias de seguridad y monitoreo.
- Aplica límites de uso y registros de auditoría.
- Revisa consentimiento biométrico, menores, retención y eliminación con un abogado.

## Prueba rápida local con Docker

```bash
docker build -t facefind-photos .
docker run --rm -p 8000:8000 --env-file .env facefind-photos
```

Abre `http://localhost:8000` y verifica `http://localhost:8000/health`.

## Final readiness check

After setting the environment variables, open `/readiness` on the deployed domain. It reports whether the site is ready for private HTTPS testing and whether live Stripe card sales are configured.

You may also run:

```bash
python production_check.py
```

Do not open the platform publicly until `https_public_url` and `admin_protection` both report `true`.
