import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import yfinance as yf

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("IndianFNOBot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Initialize Gemini Client if key exists
GEMINI_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
ai_client = None

if GEMINI_KEY:
    clean_key = GEMINI_KEY.strip().strip("'\"")
    try:
        from google import genai
        ai_client = genai.Client(api_key=clean_key)
        logger.info("Google GenAI client initialized.")
    except Exception as e:
        logger.warning(f"Could not initialize GenAI client: {e}")

# ── Render Health Check HTTP Server (Binds Render's Port) ────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive and listening!")

    def log_message(self, format, *args):
        return

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Render health server listening on port {port}")
    server.serve_forever()

# ── Quantitative Technical Analysis Engine (Fallback) ───────────────
def calculate_quant_setup(sym: str, hist) -> str:
    last_close = hist["Close"].iloc[-1]
    high = hist["High"].iloc[-1]
    low = hist["Low"].iloc[-1]
    
    # 20-day statistics
    high_20 = hist["High"].tail(20).max()
    low_20 = hist["Low"].tail(20).min()
    sma_20 = hist["Close"].tail(20).mean()
    sma_50 = hist["Close"].tail(50).mean() if len(hist) >= 50 else sma_20

    # Classical Floor Pivots
    pivot = (high + low + last_close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)

    bias = "BULLISH 🟢" if last_close >= sma_20 else "BEARISH 🔴"
    trend = "Above 50 SMA" if last_close >= sma_50 else "Below 50 SMA"

    return (
        f"📊 *Quantitative Setup: {sym}*\n\n"
        f"• *LTP*: ₹{last_close:.2f}\n"
        f"• *Directional Bias*: *{bias}* ({trend})\n\n"
        f"📍 *Key Levels:*\n"
        f"• *Pivot*: ₹{pivot:.2f}\n"
        f"• *Resistance 1 (R1)*: ₹{r1:.2f} | *R2*: ₹{r2:.2f}\n"
        f"• *Support 1 (S1)*: ₹{s1:.2f} | *S2*: ₹{s2:.2f}\n"
        f"• *20-Day Range*: ₹{low_20:.2f} - ₹{high_20:.2f}\n\n"
        f"🎯 *Action Plan*: Look for continuation above ₹{r1:.2f} (Target: ₹{r2:.2f}) "
        f"or long entry on support test near ₹{s1:.2f} with Stop Loss below ₹{s2:.2f}."
    )

# ── Telegram Handlers ────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    await update.message.reply_text(
        f"Hello {user}! Indian F&O Intelligence Bot is online.\n\n"
        "Commands:\n"
        "• /quote <SYM> (e.g. /quote SBIN or /quote ^NSEI)\n"
        "• /analyze <SYM> (AI trade thesis & technical setup)\n"
        "• /brief (Pre-market indices wrap)"
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
    await update.message.reply_text(f"⚡ Analyzing market data for {sym}...")

    ticker_sym = sym if sym.startswith("^") else f"{sym}.NS"
    try:
        t = yf.Ticker(ticker_sym)
        hist = t.history(period="3mo")
        if hist.empty:
            await update.message.reply_text(f"Could not retrieve market data for {sym}.")
            return

        last_close = hist["Close"].iloc[-1]
        
        # Try AI generation first if client is available
        if ai_client:
            prompt = (
                f"You are an Indian stock market quantitative analyst. "
                f"Analyze {sym} (Recent close: {last_close:.2f}). Provide:\n"
                f"1. Directional Bias (BULLISH/BEARISH/NEUTRAL)\n"
                f"2. Key Support & Resistance levels\n"
                f"3. Recommended F&O Strategy or Setup\n"
                f"4. Risk Management (Stop loss and Target)\n"
                f"Keep the formatting compact and scannable with bold points."
            )
            try:
                resp = ai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                await update.message.reply_text(f"📈 *Trade Setup: {sym}*\n\n{resp.text}", parse_mode="Markdown")
                return
            except Exception as ai_err:
                logger.warning(f"AI generation skipped due to: {ai_err}. Switching to Quant engine.")

        # Reliable instant quantitative analysis fallback
        quant_report = calculate_quant_setup(sym, hist)
        await update.message.reply_text(quant_report, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"Analysis failed: {e}")

async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌅 Generating market wrap...")
    try:
        nifty = yf.Ticker("^NSEI").fast_info
        banknifty = yf.Ticker("^NSEBANK").fast_info

        n_chg = ((nifty.last_price - nifty.previous_close) / nifty.previous_close) * 100
        b_chg = ((banknifty.last_price - banknifty.previous_close) / banknifty.previous_close) * 100
        n_sign = "+" if n_chg >= 0 else ""
        b_sign = "+" if b_chg >= 0 else ""

        # Check AI summary
        if ai_client:
            prompt = (
                f"Provide a concise 3-bullet pre-market outlook for Indian Markets today. "
                f"Current Nifty: {nifty.last_price:.2f} ({n_sign}{n_chg:.2f}%), "
                f"Bank Nifty: {banknifty.last_price:.2f} ({b_sign}{b_chg:.2f}%). "
                f"Highlight bias and key levels."
            )
            try:
                resp = ai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                await update.message.reply_text(f"🌅 *Market Outlook*\n\n{resp.text}", parse_mode="Markdown")
                return
            except Exception as ai_err:
                logger.warning(f"AI brief failed: {ai_err}. Falling back to index numbers.")

        # Fallback index numbers
        report = (
            "🌅 *Market Wrap*\n\n"
            f"• *NIFTY 50*: ₹{nifty.last_price:.2f} ({n_sign}{n_chg:.2f}%)\n"
            f"• *BANK NIFTY*: ₹{banknifty.last_price:.2f} ({b_sign}{b_chg:.2f}%)\n\n"
            "Use `/analyze <SYM>` for individual stock pivot levels."
        )
        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Brief generation failed: {e}")

# ── Main Entrypoint ──────────────────────────────────────────────────
def main():
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quote", quote))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("brief", brief))

    logger.info("Bot starting polling loop...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()