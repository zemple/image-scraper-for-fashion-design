import asyncio
import logging
import json
import os
import re
import random
import sys
import aiohttp
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed

# Logger setup
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_cookies():
    script_dir = os.path.dirname(os.path.realpath(__file__))
    cookie_file_path = os.path.join(script_dir, 'xhs_cookies.txt')
    try:
        with open(cookie_file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Cookie file not found: {cookie_file_path}")
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in cookie file: {cookie_file_path}")
    return {}

def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "", filename)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def load_page(page, url):
    logger.info(f"Attempting to load page: {url}")
    try:
        await page.goto(url, timeout=90000, wait_until="domcontentloaded")
        await page.wait_for_selector('body', timeout=90000)
        logger.info("Page loaded")
    except PlaywrightTimeoutError as e:
        logger.error(f"Timeout error loading page {url}: {e}")
        raise
    except PlaywrightError as e:
        logger.error(f"Playwright error loading page {url}: {e}")
        raise

async def extract_element_text(page, selector):
    element = await page.query_selector(selector)
    return await element.text_content() if element else "Not available"

async def extract_user_info(page):
    info = {}
    selectors = {
        "User Name": ".user-name", 
        "Account number": ".user-redId",
        "IP Location": ".user-IP", 
        "User Description": ".user-desc",
        "Gender and Tag": ".tag-item",
    }
    for key, selector in selectors.items():
        info[key] = await extract_element_text(page, selector)
        logger.debug(f"Extracted {key}: {info[key]}")

    interactions = await page.query_selector_all('.data-info .count')
    info["Following"] = await interactions[0].text_content() if len(interactions) > 0 else "Not available"
    info["Fans"] = await interactions[1].text_content() if len(interactions) > 1 else "Not available"
    info["Likes and Collects"] = await interactions[2].text_content() if len(interactions) > 2 else "Not available"

    return info

async def extract_post_urls(page):
    post_urls = set()
    scroll_attempts = 0
    max_scroll_attempts = 10

    while scroll_attempts < max_scroll_attempts:
        elements = await page.query_selector_all('a[href^="/explore/"]')
        new_urls = {await element.get_attribute('href') for element in elements}
        post_urls.update(new_urls)

        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await page.wait_for_timeout(2000)
        new_height = await page.evaluate('document.body.scrollHeight')

        if new_height == await page.evaluate('window.innerHeight + window.scrollY'):
            logger.info("Reached end of page or no new content loaded")
            break
        scroll_attempts += 1

    full_post_urls = [f"https://www.xiaohongshu.com{url}" for url in post_urls]
    logger.info(f"Extracted {len(full_post_urls)} post URLs")
    return full_post_urls

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def download_image(session, url, save_path):
    try:
        async with session.get(url, ssl=False) as response:
            if response.status == 200:
                content = await response.read()
                if len(content) == 0:
                    raise aiohttp.ClientPayloadError("Received empty response")
                with open(save_path, 'wb') as f:
                    f.write(content)
                logger.info(f"Image downloaded: {save_path}")
            else:
                logger.error(f"Failed to download image: {url} - Status code: {response.status}")
                raise aiohttp.ClientError(f"Status code: {response.status}")
    except (aiohttp.ClientError, aiohttp.ClientPayloadError, ConnectionResetError) as e:
        logger.error(f"Error downloading image {url}: {e}")
        raise

async def download_video(session, url, save_path):
    try:
        async with session.get(url, ssl=False) as response:
            if response.status == 200:
                with open(save_path, 'wb') as f:
                    f.write(await response.read())
                logger.info(f"Video downloaded: {save_path}")
            else:
                logger.error(f"Failed to download video: {url}")
    except aiohttp.ClientError as e:
        logger.error(f"Error downloading video {url}: {e}")

async def scrape_post(page, post_url, user_folder):
    logger.info(f"Scraping post: {post_url}")
    try:
        await load_page(page, post_url)

        if "login" in page.url or await page.query_selector('.captcha-container'):
            raise Exception("Anti-bot measure detected")

        await page.wait_for_selector('body', timeout=90000)
        post_info = await extract_post_info(page)

        post_id = post_url.split('/')[-1]
        post_title = post_info.get('title', '').strip() or f'post_{post_id}'
        post_folder_name = sanitize_filename(f"{post_title}_{post_id}")
        post_folder = os.path.join(user_folder, post_folder_name)
        os.makedirs(post_folder, exist_ok=True)
        
        with open(os.path.join(post_folder, 'post_info.txt'), 'w', encoding='utf-8') as f:
            f.write(f"Post URL: {post_url}\n\n")
            for key, value in post_info.items():
                if isinstance(value, list):
                    f.write(f"{key}:\n")
                    for item in value:
                        f.write(f"- {item}\n")
                else:
                    f.write(f"{key}: {value}\n")

        video_url = await page.evaluate('''() => {
            let videoMeta = document.querySelector('meta[name="og:video"]');
            return videoMeta ? videoMeta.content : null;
        }''')

        if video_url:
            logger.debug(f"Found video: {video_url}")
            async with aiohttp.ClientSession() as session:
                video_path = os.path.join(post_folder, "video.mp4")
                await download_video(session, video_url, video_path)
            logger.info(f"Video saved for: {post_url}")
        else:
            previous_height = await page.evaluate("document.body.scrollHeight")
            while True:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)
                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height == previous_height:
                    break
                previous_height = new_height

            img_urls = set()
            image_elements = await page.query_selector_all('img')
            for img in image_elements:
                src = await img.get_attribute('src')
                if src and 'webpic' in src:
                    img_urls.add(src)

            logger.debug(f"Extracted image elements: {list(img_urls)}")

            async with aiohttp.ClientSession() as session:
                tasks = [download_image(session, url, os.path.join(post_folder, f"image_{i+1}.jpg")) for i, url in enumerate(img_urls)]
                await asyncio.gather(*tasks)

            logger.info(f"Post info and images saved for: {post_url}")
        return True
    except PlaywrightTimeoutError as e:
        logger.error(f"Timeout error scraping post {post_url}: {e}")
    except PlaywrightError as e:
        logger.error(f"Playwright error scraping post {post_url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error scraping post {post_url}: {e}")
    return False


async def extract_post_info(page):
    post_info = {}
    selectors = {
        'title': '#detail-title',
        'description': 'span[data-v-6b50f68a]',
        'date': 'span.date',
    }
    for key, selector in selectors.items():
        post_info[key] = await extract_element_text(page, selector)

    interactions = await page.query_selector_all('.left .count')
    if len(interactions) >= 3:
        post_info['likes'] = await extract_number(interactions[0])
        post_info['collects'] = await extract_number(interactions[1])
        post_info['comments'] = await extract_number(interactions[2])
    else:
        post_info['likes'] = post_info['collects'] = post_info['comments'] = "N/A"

    tags = await page.query_selector_all('a.tag')
    post_info['tags'] = [await tag.text_content() for tag in tags]

    return post_info

async def extract_number(element):
    text = await element.text_content()
    number = ''.join(filter(str.isdigit, text))
    return number if number else "0"

async def scrape_xhs_profile(url):
    logger.info(f"Starting scrape for URL: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')

        cookies = load_cookies()
        if cookies:
            await context.add_cookies([{"name": k, "value": v, "domain": ".xiaohongshu.com", "path": "/"} for k, v in cookies.items()])
        else:
            logger.error("No cookies loaded. Scraping may fail.")
        
        page = await context.new_page()

        try:
            await load_page(page, url)
            info = await extract_user_info(page)
            post_urls = await extract_post_urls(page)

            user_name = info.get("User Name", "unknown_user").strip()
            user_folder = os.path.join('/Users/yz/Desktop/spider/xhs_profiles', sanitize_filename(user_name))
            os.makedirs(user_folder, exist_ok=True)

            with open(os.path.join(user_folder, 'user_info.txt'), 'w', encoding='utf-8') as f:
                f.write(f"Profile URL: {url}\n\n")
                for key, value in info.items():
                    f.write(f"{key}: {value.strip()}\n")
                f.write(f"\nTotal Posts: {len(post_urls)}\n")

            logger.info(f"User info saved to {user_folder}")

            for post_url in post_urls:
                if not await scrape_post(page, post_url, user_folder):
                    logger.warning(f"Failed to scrape post {post_url}")
                await asyncio.sleep(random.uniform(2, 5))

        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
        finally:
            await browser.close()
            logger.info("Browser closed")

async def main():
    urls = [
        
        "https://www.xiaohongshu.com/user/profile/5e47d86c000000000100013d"
    ]
    tasks = [scrape_xhs_profile(url) for url in urls]
    await asyncio.gather(*tasks)
    print("Scraping completed. Check the Desktop for the output files.")

if __name__ == "__main__":
    asyncio.run(main())