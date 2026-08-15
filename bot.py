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

def main_menu():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🚀 بدء فحص ملف جديد", callback_data="start_check"),
        InlineKeyboardButton("ℹ️ معلومات البوت", callback_data="bot_info")
    )
    return keyboard

def input_method():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("📄 إرسال ملف", callback_data="send_file"),
        InlineKeyboardButton("📝 كتابة النص", callback_data="send_text")
    )
    return keyboard

def result_actions(nftoken):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("📱 نسخ رابط الهاتف", callback_data=f"copy_phone:{nftoken}"),
        InlineKeyboardButton("💻 نسخ رابط الكمبيوتر", callback_data=f"copy_pc:{nftoken}"),
        InlineKeyboardButton("📺 نسخ رابط التلفاز", callback_data=f"copy_tv:{nftoken}"),
        InlineKeyboardButton("🔑 نسخ nftoken", callback_data=f"copy_token:{nftoken}"),
        InlineKeyboardButton("🔄 فحص كوكيز آخر", callback_data="start_check")
    )
    return keyboard

async def extract_nftoken(cookie_str: str) -> str:
    """استخراج nftoken من الكوكيز بسرعة"""
    cookies_dict = {}
    for cookie in cookie_str.split(';'):
        cookie = cookie.strip()
        if '=' in cookie:
            name, value = cookie.split('=', 1)
            cookies_dict[name.strip()] = value.strip()

    if 'nftoken' in cookies_dict:
        return cookies_dict['nftoken']

    netflix_id = cookies_dict.get('NetflixId', '')
    secure_netflix_id = cookies_dict.get('SecureNetflixId', '')

    if netflix_id and secure_netflix_id:
        return f"{netflix_id}|{secure_netflix_id}"

    flwssn = cookies_dict.get('flwssn', '')
    if flwssn:
        return flwssn

    return ''

async def check_netflix_cookie(cookie_str: str) -> dict:
    """فحص سريع للكوكيز"""
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
        'nftoken': None,
        'netflix_id': None,
        'error': None
    }

    timeout = aiohttp.ClientTimeout(total=8)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get('https://www.netflix.com/YourAccount', headers=headers) as resp:
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
        except asyncio.TimeoutError:
            result['error'] = "انتهت مهلة الفحص"
        except Exception as e:
            result['error'] = str(e)

        if result['valid']:
            result['nftoken'] = await extract_nftoken(cookie_str)

            cookies_dict = {}
            for cookie in cookie_str.split(';'):
                cookie = cookie.strip()
                if '=' in cookie:
                    name, value = cookie.split('=', 1)
                    cookies_dict[name.strip()] = value.strip()
            result['netflix_id'] = cookies_dict.get('NetflixId', '')

    return result

async def check_multiple_cookies(cookies_list: list) -> list:
    """فحص عدة كوكيز بالتوازي"""
    tasks = [check_netflix_cookie(cookie) for cookie in cookies_list]
    return await asyncio.gather(*tasks)

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    welcome_text = """
🎬 **مرحباً بك في بوت فحص كوكيز نتفليكس**

اضغط على زر **بدء الفحص** لإرسال الكوكيز الخاص بك.

بعد الفحص ستحصل على:
✅ معلومات الحساب
🔑 nftoken
📱 روابط تسجيل دخول لجميع الأجهزة
    """
    await message.reply(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())

@dp.callback_query_handler(lambda c: c.data == 'bot_info')
async def process_bot_info(callback_query: types.CallbackQuery):
    await callback_query.answer()
    info_text = """
ℹ️ **معلومات البوت**

هذا البوت يقوم بفحص كوكيز نتفليكس واستخراج:
- معلومات الحساب
- nftoken
- روابط تسجيل دخول لجميع الأجهزة
    """
    await callback_query.message.edit_text(info_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())

@dp.callback_query_handler(lambda c: c.data == 'start_check')
async def process_start_check(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.edit_text(
        "🚀 **بدء فحص ملف جديد**\n\nاختر طريقة إرسال الكوكيز:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=input_method()
    )

@dp.callback_query_handler(lambda c: c.data == 'send_file')
async def process_send_file(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.edit_text(
        "📄 **أرسل الملف الآن**\n\nأرسل ملف يحتوي على كوكيز (كل سطر كوكيز منفصل)",
        parse_mode=ParseMode.MARKDOWN
    )
    await Form.waiting_cookie_file.set()

@dp.callback_query_handler(lambda c: c.data == 'send_text')
async def process_send_text(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.edit_text(
        "📝 **أرسل الكوكيز الآن**\n\nالصق الكوكيز مباشرة في الرسالة",
        parse_mode=ParseMode.MARKDOWN
    )
    await Form.waiting_cookies.set()

@dp.message_handler(state=Form.waiting_cookies, content_types=types.ContentTypes.TEXT)
async def process_text_cookies(message: types.Message, state: FSMContext):
    cookie_str = message.text.strip()

    # رد فوري
    processing_msg = await message.reply("⏳ **جاري الفحص...**", parse_mode=ParseMode.MARKDOWN)

    result = await check_netflix_cookie(cookie_str)

    await processing_msg.delete()

    if result['valid']:
        nftoken = result.get('nftoken', '')

        result_text = f"""
✅ **فحص ناجح!**

📧 **الإيميل:** `{result['email'] or 'غير متوفر'}`
💳 **الخطة:** `{result['plan'] or 'غير متوفر'}`
🌍 **الدولة:** `{result['country'] or 'غير متوفر'}`

🔑 **nftoken:**
`{nftoken or 'غير متوفر'}`

👇 **اضغط على الأزرار بالأسفل لعرض روابط النسخ:**
        """

        await message.reply(
            result_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=result_actions(nftoken)
        )
    else:
        await message.reply(
            f"❌ **فشل الفحص**\n\n**السبب:** `{result['error'] or 'كوكيز غير صالح'}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu()
        )

    await state.finish()

@dp.message_handler(state=Form.waiting_cookie_file, content_types=types.ContentTypes.DOCUMENT)
async def process_cookie_file(message: types.Message, state: FSMContext):
    # رد فوري
    processing_msg = await message.reply("⏳ **جاري تحميل الملف...**", parse_mode=ParseMode.MARKDOWN)

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

    # فحص متوازي
    status_msg = await message.reply(f"⏳ **جاري فحص {len(cookies_list)} كوكيز...**", parse_mode=ParseMode.MARKDOWN)

    results = await check_multiple_cookies(cookies_list)

    await status_msg.delete()

    results_text = "📊 **نتائج الفحص:**\n\n"
    valid_count = 0

    for i, result in enumerate(results, 1):
        if result['valid']:
            valid_count += 1
            nftoken = result.get('nftoken', '')
            results_text += f"""
✅ **كوكيز {i}:**
📧 `{result['email'] or 'N/A'}`
💳 `{result['plan'] or 'N/A'}`
🔑 `{nftoken[:50]}...`
🔗 https://netflix.com/?nftoken={nftoken}
---
"""
        else:
            results_text += f"❌ **كوكيز {i}:** غير صالح\n---\n"

    results_text += f"\n📈 **الإجمالي:** {valid_count}/{len(cookies_list)} صالح"

    if len(results_text) > 4000:
        parts = [results_text[i:i+4000] for i in range(0, len(results_text), 4000)]
        for part in parts:
            await message.reply(part, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(results_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())

    await state.finish()

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('copy_'))
async def process_copy_buttons(callback_query: types.CallbackQuery):
    await callback_query.answer()

    data = callback_query.data
    parts = data.split(':', 1)

    if len(parts) < 2:
        await callback_query.answer("خطأ", show_alert=True)
        return

    action = parts[0]
    nftoken = parts[1] if len(parts) > 1 else ''

    base_url = "https://netflix.com/?nftoken="
    link = base_url + nftoken

    if action == 'copy_token':
        copy_text = nftoken
        label = "🔑 **nftoken**"
    elif action == 'copy_phone':
        copy_text = link
        label = "📱 **رابط الهاتف**"
    elif action == 'copy_pc':
        copy_text = link
        label = "💻 **رابط الكمبيوتر**"
    elif action == 'copy_tv':
        copy_text = link
        label = "📺 **رابط التلفاز**"
    else:
        copy_text = nftoken
        label = "🔑 **nftoken**"

    await callback_query.message.reply(
        f"{label}:\n\n`{copy_text}`\n\n⚠️ **اضغط مطولاً على النص للنسخ**",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message_handler(commands=['cancel'], state='*')
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await message.reply("❌ **تم الإلغاء**", reply_markup=main_menu())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
