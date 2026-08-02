# Corrección PRO Secure v8.1

Problema corregido:
- La página podía mostrar "Page Unresponsive".
- El observador de traducción volvía a ejecutar la traducción repetidamente.
- Eso bloqueaba el navegador y evitaba que eventos, precios, órdenes y controles dinámicos terminaran de cargar.

Solución:
- Traducción protegida contra ciclos repetidos.
- Actualizaciones agrupadas con requestAnimationFrame.
- El observador se desconecta mientras traduce y luego se vuelve a conectar.
- Nueva versión de caché/service worker para eliminar el JavaScript anterior.
