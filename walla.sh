#!/data/data/com.termux/files/usr/bin/bash
# WallaBot: lo mantiene SIEMPRE encendido (si se cierra, vuelve a arrancar a los 5 s).
# El código viene de GitHub y se actualiza solo; ya no se usan archivos de Descargas.
for p in $(pgrep -f "walla.sh"); do [ "$p" != "$$" ] && kill "$p" 2>/dev/null; done
pkill -f wallabot.py
rm -f ~/downloads/wallabot*.py* ~/storage/downloads/wallabot*.py* 2>/dev/null
if ! grep -q '^VERSION = ' ~/wallabot.py 2>/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/itzzpauu/wallabot/main/wallabot.py -o ~/wallabot.py && echo "✅ Bot descargado de GitHub"
fi
termux-wake-lock 2>/dev/null
while true; do
  python ~/wallabot.py
  echo "⚠️ El bot se cerró. Lo vuelvo a encender en 5 segundos..."
  sleep 5
done
