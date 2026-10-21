# WallaBot

Bot personal de alertas de **Wallapop (España e Italia)** y **Vinted (todos los países)** en Telegram, con panel web en `localhost:8080`.

## Instalar en Termux (Android)

```
curl -fsSL https://raw.githubusercontent.com/itzzpauu/wallabot/main/instalar.sh | bash
```

Después, para encenderlo: `walla`

El bot se actualiza solo desde este repositorio cada 10 minutos (o con `/actualizar` en Telegram).
Las alertas y el token se guardan en el teléfono (`~/.wallabot`), nunca aquí.
