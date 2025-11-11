import logging
import os
import aiohttp
from flask import Flask
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
TOKEN = "8511981048:AAGzbSxd1BpRLfqxXiibV2DuG3g6p5bsbBk"
ALPHA_VANTAGE_KEY = "TKY88GBALL8517UQ"  # https://www.alphavantage.co/support/#api-key
# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
user_data = {}

main_keyboard = [
    [KeyboardButton("EURUSD"), KeyboardButton("GBPUSD")],
    [KeyboardButton("NZDUSD"), KeyboardButton("EURGBP")]
]
reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)

# Flask для health check Render (слушает порт 10000)
flask_app = Flask(__name__)

@flask_app.route('/', defaults={'path': ''})
@flask_app.route('/<path:path>')
def catch_all(path):
    return "Bot is alive! 🚀", 200

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False)


async def get_gbp_usd_rate():
    url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency=GBP&to_currency=USD&apikey={ALPHA_VANTAGE_KEY}"
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "Realtime Currency Exchange Rate" in data:
                        rate = float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
                        logging.info(f"Alpha Vantage: GBPUSD = {rate:.6f}")
                        return rate
    except:
        pass
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Risk-Manager v1.0\n"
        "Choose the pair:",
        reply_markup=reply_markup
    )


async def choose_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pair = update.message.text.upper()
    if pair not in ["EURUSD", "GBPUSD", "NZDUSD", "EURGBP"]:
        await update.message.reply_text("Нажми кнопку с парой")
        return ConversationHandler.END

    user_data[update.effective_user.id] = {"pair": pair}
    await update.message.reply_text(f"Step 1/3\nBalance in USD:")
    return "balance"


async def get_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    if not text.replace(".", "").isdigit():
        await update.message.reply_text("Ошибка! Только число (например: 10000)")
        return "balance"

    user_data[update.effective_user.id]["balance"] = float(text)
    await update.message.reply_text("Step 2/3\nRisk-Reward (RR ≥ 1.5):")
    return "rr"


async def get_rr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    if not text.replace(".", "").replace("-", "").isdigit():
        await update.message.reply_text("Ошибка! Введи число ≥ 1.5 (например: 2.0)")
        return "rr"

    rr = float(text)
    if rr < 1.5:
        await update.message.reply_text("RR должен быть ≥ 1.5! Попробуй 2.0, 3.0 и т.д.")
        return "rr"

    user_data[update.effective_user.id]["rr"] = rr
    await update.message.reply_text("Step 3/3\nStop-loss in pips:")
    return "stop"


async def get_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Только целое число пипсов!")
        return "stop"

    uid = update.effective_user.id
    data = user_data[uid]
    pair = data["pair"]
    balance = data["balance"]
    rr = data["rr"]
    stop_pips = int(text)

    # === ТВОЯ ФОРМУЛА: SL% = 1.5 / RR ===
    sl_percent = 1.5 / rr
    risk_money = balance * sl_percent / 100

    # === Расчёт стоимости пипса ===
    if pair in ["EURUSD", "GBPUSD", "NZDUSD"]:
        pip_value_1lot = 10.0
        base_currency = pair[:3]

    elif pair == "EURGBP":
        gbp_usd = await get_gbp_usd_rate()
        if not gbp_usd:
            await update.message.reply_text("Ошибка: нет курса GBPUSD (лимит Alpha Vantage). Попробуй позже.")
            return "stop"
        pip_value_1lot = 10.0 * gbp_usd  # ПРАВИЛЬНО: × GBPUSD
        base_currency = "EUR"
    else:
        pip_value_1lot = 10.0
        base_currency = pair[:3]

    # === Размер позиции ===
    lot_size = risk_money / (stop_pips * pip_value_1lot)
    if lot_size < 0.01:
        lot_size = 0.01
        warning = "\nМинимальный лот 0.01 — поднят автоматически"
    else:
        lot_size = round(lot_size, 2)
        warning = ""

    # === Вывод ===
    result = (
        f"Great! {pair}\n\n"
        f"Balance: ${balance:,.0f}\n"
        f"Risk: ${risk_money:.2f} ({sl_percent:.3f}%)\n"
        f"Stop-Loss: {stop_pips} pips\n\n"
        f"Recommended volume:\n"
        f"{lot_size} lots\n"
        f"({lot_size * 100_000:,} {base_currency}){warning}\n\n"
        f"{f'GBPUSD: {gbp_usd:.6f}' if pair == 'EURGBP' else ''}\n\n"
    )

    await update.message.reply_text(result, reply_markup=reply_markup)
    del user_data[uid]
    return ConversationHandler.END


# ConversationHandler
conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(EURUSD|GBPUSD|NZDUSD|EURGBP)$"), choose_pair)],
    states={
        "balance": [MessageHandler(filters.TEXT & ~filters.COMMAND, get_balance)],
        "rr": [MessageHandler(filters.TEXT & ~filters.COMMAND, get_rr)],
        "stop": [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stop)],
    },
    fallbacks=[],
)


def main():
    # Запуск Flask в фоне
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Telegram polling (без изменений)
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    print("Бот v3.1 — 100% РАБОТАЕТ НА RENDER 24/7!")
    
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    main()
