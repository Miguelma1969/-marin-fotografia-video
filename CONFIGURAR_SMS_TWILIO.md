# Configurar mensajes SMS automáticos

El código ya contiene la integración, pero los SMS no se envían hasta crear y configurar una cuenta de Twilio.

## Variables de Render

```text
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1...
TWILIO_MESSAGING_SERVICE_SID=
PHOTOGRAPHER_PHONE=+17133781730
```

Puedes utilizar `TWILIO_FROM_NUMBER` o un `TWILIO_MESSAGING_SERVICE_SID`. No es necesario llenar ambos.

Después de guardar las variables:

1. Presiona **Save and deploy** en Render.
2. Abre **Panel del fotógrafo → Orders**.
3. Presiona **Probar SMS**.
4. Revisa Render Logs buscando `[sms] queued` o `[sms] failed`.

## Importante

El número desde el cual salen los mensajes debe ser un número habilitado en Twilio. `PHOTOGRAPHER_PHONE` es el número que recibe tus avisos.
