#!/data/data/com.termux/files/usr/bin/bash
# WallaBot: lo mantiene SIEMPRE encendido (si se cierra, vuelve a arrancar a los 5 s).
for p in $(pgrep -f "walla.sh"); do [ "$p" != "$$" ] && kill "$p" 2>/dev/null; done
pkill -f wallabot.py
f=$(ls -t ~/downloads/wallabot* ~/storage/downloads/wallabot* 2>/dev/null | grep -v -e '\.json' -e '\.txt' -e '\.log' | head -1)
if [ -n "$f" ]; then cp "$f" ~/wallabot.py && rm -f "$f" && echo "✅ Actualizado desde Descargas"; fi
[ -f ~/wallabot.py ] || curl -fsSL https://raw.githubusercontent.com/itzzpauu/wallabot/main/wallabot.py -o ~/wallabot.py
termux-wake-lock 2>/dev/null
while true; do
  python ~/wallabot.py
  echo "⚠️ El bot se cerró. Lo vuelvo a encender en 5 segundos..."
  sleep 5
done
