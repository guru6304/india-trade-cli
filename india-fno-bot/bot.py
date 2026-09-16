import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import yfinance as yf
from google import genai

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("IndianFNOBot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Check all common environment variable names for the Gemini key
GEMINI_KEY = (
    os.getenv("GEMINI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or os.getenv("GEMINI_KEY")
)

if not GEMINI_KEY:
    logger.warning("No Gemini API key detected! Set GEMINI_API_KEY in Render.")
    ai_client = None
else:
    # Clean any accidental quotes or whitespace
    clean_key = GEMINI_KEY.strip().strip("'\"")
    ai_client = genai.Client(api_key=clean_key)

# ── Render Health Check HTTP Server ──────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive and listening!")

    def log_message(self, format, *args):
        # Silence raw HTTP request logs to keep terminal/console clean
        return

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Render health server listening on port {port}")
    server.serve_forever()

# ── Telegram Handlers ────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    await update.message.reply_text(
        f"Hello {user}! Indian F&O Intelligence Bot is online.\n\n"
        "Commands:\n"
        "• /quote <SYM> (e.g. /quote SBIN or /quote ^NSEI)\n"
        "• /analyze <SYM> (AI trade thesis & F&O setup)\n"
        "• /brief (Pre-market wrap)"
    )

async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /quote <SYM> (e.g. /quote RELIANCE or /quote ^NSEI)")
        return
    sym = context.args[0].upper()
    ticker_sym = sym if sym.startswith("^") else f"{sym}.NS"
    
    try:
        t = yf.Ticker(ticker_sym)
        data = t.fast_info
        last_price = data.last_price
        prev_close = data.previous_close
        chg = ((last_price - prev_close) / prev_close) * 100
        sign = "+" if chg >= 0 else ""
        await update.message.reply_text(f"📊 *{sym}*\nLTP: ₹{last_price:.2f} ({sign}{chg:.2f}%)", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error fetching quote for {sym}: {e}")

async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /analyze <SYM> (e.g. /analyze INFY)")
        return
    sym = context.args[0].upper()
    await update.message.reply_text(f"🤖 Gemini is generating trade thesis for {sym}...")

    ticker_sym = sym if sym.startswith("^") else f"{sym}.NS"
    t = yf.Ticker(ticker_sym)
    hist = t.history(period="1mo")
    
    if hist.empty:
        await update.message.reply_text("Could not retrieve market data.")
        return

    last_close = hist["Close"].iloc[-1]
    prompt = (
        f"You are an Indian F&O quantitative trader. "
        f"Analyze {sym} (Recent close: {last_close:.2f}). Provide:\n"
        f"1. Directional Bias (BULLISH/BEARISH/NEUTRAL)\n"
        f"2. Key Support & Resistance levels\n"
        f"3. Recommended F&O Strategy (Strike selection / Option buy/sell/spread)\n"
        f"4. Risk Management (Stop loss and Target)\n"
        f"Keep the formatting compact and easily scannable on mobile with bold points."
    )
    
    try:
        resp = ai_client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        await update.message.reply_text(f"📈 *Trade Setup: {sym}*\n\n{resp.text}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"AI Generation failed: {e}")

async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌅 Pulling pre-market wrap...")
    prompt = (
        "Provide a concise pre-market brief for Indian Stock Market (Nifty 50, Bank Nifty). "
        "Summarize expected bias, global cues, crude oil impact, and key support/resistance zones for today."
    )
    try:
        resp = ai_client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        await update.message.reply_text(f"🌅 *Pre-Market Briefing*\n\n{resp.text}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Brief generation failed: {e}")

# ── Main Entrypoint ──────────────────────────────────────────────────
def main():
    # 1. Start the HTTP server in a background daemon thread for Render
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()

    # 2. Start the Telegram Bot Polling
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quote", quote))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("brief", brief))

    logger.info("Bot starting polling loop...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()