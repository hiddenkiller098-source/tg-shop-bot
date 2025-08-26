import os
import json
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiocryptopay import AioCryptoPay, Networks

# ===== Env =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")
BASE_URL = os.getenv("BASE_URL", "")  # بعداً می‌ذاریم
TG_WEBHOOK_SECRET = os.getenv("TG_WEBHOOK_SECRET", "change-me")

WEBHOOK_PATH = "/webhook/telegram"
CRYPTO_WEBHOOK_PATH = "/webhook/cryptopay"

# ===== Init =====
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

cpay = AioCryptoPay(token=CRYPTO_PAY_TOKEN, network=Networks.MAIN_NET)

# فروشگاه: شناسه -> (عنوان، قیمت USDT)
PRODUCTS = {
    "p1": ("محصول ۱", 50),
    "p2": ("محصول ۲", 80),
    "p3": ("محصول ۳", 199),
}

def shop_keyboard():
    kb = InlineKeyboardBuilder()
    for pid, (title, price) in PRODUCTS.items():
        kb.button(text=f"{title} — {price} USDT", callback_data=f"buy:{pid}")
    kb.adjust(1)
    return kb.as_markup()

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer(
        "سلام! به فروشگاه خوش اومدی. یکی از محصولات زیر رو انتخاب کن:",
        reply_markup=shop_keyboard()
    )

@dp.callback_query(F.data.startswith("buy:"))
async def on_buy(cq: CallbackQuery):
    pid = cq.data.split(":")[1]
    title, price = PRODUCTS[pid]

    invoice = await cpay.create_invoice(
        asset="USDT",
        amount=price,
        description=f"{title} - سفارش کاربر {cq.from_user.id}",
        payload=f"user={cq.from_user.id}&product={pid}",
        allow_anonymous=True
    )

    pay_url = invoice.pay_url
    text = (
        f"✅ سفارش: *{title}*\n"
        f"مبلغ: *{price} USDT*\n\n"
        f"برای پرداخت روی لینک زیر بزن:\n{pay_url}\n\n"
        "پس از پرداخت، تأییدیه به‌صورت خودکار ارسال می‌شود."
    )
    await cq.message.answer(text, parse_mode="Markdown")
    await cq.answer()

# ===== Webhooks =====
async def telegram_webhook(request: web.Request):
    # تأیید هدر امنیتی وبهوک تلگرام
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TG_WEBHOOK_SECRET:
        return web.Response(status=401, text="unauthorized")
    update = await request.json()
    await dp.feed_webhook_update(bot, update)
    return web.Response(text="ok")

async def cryptopay_webhook(request: web.Request):
    try:
        data = await request.json()
        invoice = data.get("invoice") or {}
        status = invoice.get("status")
        payload = invoice.get("payload") or ""
        params = dict(p.split("=", 1) for p in payload.split("&") if "=" in p)

        if status == "paid":
            user_id = int(params.get("user"))
            pid = params.get("product")
            title, price = PRODUCTS.get(pid, ("محصول", ""))
            await bot.send_message(
                chat_id=user_id,
                text=f"🎉 پرداخت شما برای *{title}* با مبلغ *{price} USDT* دریافت شد. سفارش ثبت گردید.",
                parse_mode="Markdown"
            )
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)

async def on_startup(app: web.Application):
    if BASE_URL:
        await bot.set_webhook(
            url=f"{BASE_URL}{WEBHOOK_PATH}",
            secret_token=TG_WEBHOOK_SECRET
        )

async def on_shutdown(app: web.Application):
    await bot.delete_webhook(drop_pending_updates=True)
    await cpay.close()

def build_app():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, telegram_webhook)
    app.router.add_post(CRYPTO_WEBHOOK_PATH, cryptopay_webhook)
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
