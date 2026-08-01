# Subir a GitHub desde iPhone o computadora

Repositorio recomendado: `marin-photo-platform`

## Desde el sitio web de GitHub

1. Inicia sesión en GitHub.
2. Crea un repositorio nuevo llamado `marin-photo-platform`.
3. Déjalo público o privado y no agregues README, .gitignore ni licencia desde GitHub.
4. Abre el repositorio y selecciona **Add file → Upload files**.
5. Descomprime este ZIP primero y sube el contenido de la carpeta `Marin-Fotografia-y-Video-Complete`.
6. Confirma que `render.yaml`, `requirements.txt`, `Dockerfile` y la carpeta `app` estén en la raíz del repositorio.
7. Presiona **Commit changes**.

## Conectar con Render

1. En Render selecciona **New + → Blueprint** o **Web Service**.
2. Conecta el repositorio `marin-photo-platform`.
3. Si usas Blueprint, Render detectará `render.yaml`.
4. Configura las variables secretas indicadas en `.env.example`.
5. Publica y abre la dirección HTTPS asignada por Render.

Nunca subas un archivo `.env` real ni claves de Stripe, correo o administrador a GitHub.
