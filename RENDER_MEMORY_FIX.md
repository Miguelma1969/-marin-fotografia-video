# Corrección de memoria para Render

Esta versión corrige las dos causas observadas en los registros:

1. **Reinicio por memoria:** ya no usa `buffalo_l`. Usa `buffalo_sc`, carga únicamente detección y reconocimiento, limita los hilos de ONNX/BLAS y reduce las imágenes antes del análisis.
2. **Eventos que desaparecen después de reiniciar:** la aplicación acepta `DATA_DIR=/var/data` y `render.yaml` adjunta un disco persistente en esa ruta.

## Cambios importantes

- El modelo facial se descarga durante la construcción de Docker, no durante una solicitud del cliente.
- Uvicorn se ejecuta con un solo worker.
- El tamaño de detección baja de 640×640 a 320×320.
- Las fotografías grandes se decodifican y reducen a un máximo configurable antes de usar ONNX.
- El sitio, los pedidos, eventos, fotos y videos se guardan bajo `/var/data` en Render.

## Después de subir el ZIP a GitHub

En el servicio existente de Render, verifica estas variables:

```text
DATA_DIR=/var/data
FACE_MODEL=buffalo_sc
FACE_MODEL_ROOT=/opt/insightface
FACE_DET_SIZE=320
FACE_MAX_IMAGE_DIM=2000
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
MALLOC_ARENA_MAX=2
```

También debes adjuntar un disco persistente con **Mount Path** `/var/data`. Sin el disco, el servicio funcionará, pero los eventos y archivos nuevos volverán a desaparecer tras un reinicio o despliegue.

## Verificación

Después del despliegue:

1. Abre `/health`. Debe mostrar `face_model: buffalo_sc`.
2. Crea un evento de prueba y guarda su enlace QR.
3. Sube una fotografía de prueba.
4. Reinicia el servicio desde Render.
5. Abre nuevamente el enlace `/e/ID_DEL_EVENTO`. Debe continuar funcionando.

## Compatibilidad de índices

Los embeddings creados con `buffalo_l` no deben mezclarse con los de `buffalo_sc`. Si ya habías indexado fotografías reales con el modelo anterior, vuelve a subirlas para crear índices nuevos con `buffalo_sc`.

## Licencia

Antes de usar reconocimiento facial comercialmente, confirma que tienes derechos comerciales para el modelo facial elegido o reemplázalo por un proveedor/modelo con licencia comercial adecuada.
