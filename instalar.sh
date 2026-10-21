#!/data/data/com.termux/files/usr/bin/bash
# Instalador de WallaBot para Termux. Uso:
#   curl -fsSL https://raw.githubusercontent.com/itzzpauu/wallabot/main/instalar.sh | bash
echo "📦 Instalando WallaBot..."
pkg install -y python termux-api curl >/dev/null 2>&1
pip install -q requests >/dev/null 2>&1
URL=https://raw.githubusercontent.com/itzzpauu/wallabot/main
curl -fsSL "$URL/wallabot.py" -o ~/wallabot.py || { echo "❌ No pude descargar el bot. ¿Hay internet?"; exit 1; }
curl -fsSL "$URL/walla.sh" -o ~/walla.sh
grep -q "alias walla=" ~/.bashrc 2>/dev/null || echo "alias walla='bash ~/walla.sh'" >> ~/.bashrc
# Arranque automático al encender el móvil (necesita la app Termux:Boot)
mkdir -p ~/.termux/boot
printf '#!/data/data/com.termux/files/usr/bin/sh\ntermux-wake-lock\nbash ~/walla.sh > ~/wallabot.log 2>&1\n' > ~/.termux/boot/walla
chmod +x ~/.termux/boot/walla
# Token del bot (solo la primera vez; se guarda en el teléfono, nunca en GitHub)
if [ ! -s ~/.wallabot/wallabot_token.txt ] && [ ! -s ~/wallabot_token.txt ]; then
  printf "🔑 Pega el token del bot de Telegram y pulsa Enter: "
  read -r TOK < /dev/tty
  mkdir -p ~/.wallabot && echo "$TOK" > ~/.wallabot/wallabot_token.txt
fi
echo "✅ WallaBot instalado. Se actualizará solo desde GitHub."
echo "▶️  Arrancando... (para encenderlo otra vez en el futuro: escribe walla)"
bash ~/walla.sh
