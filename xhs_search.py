import asyncio
import logging
import json
import os
import re
import random
import aiohttp
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed

# Logger setup
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

XHS_SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={}&source=web_search_result_notes"

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def wait_for_posts(page):
    logger.info("Waiting for post elements...")
    elements = await page.query_selector_all('a[href^="/explore/"]')
    if not elements:
        # Log the page content for debugging
        logger.warning("No post elements found. Retrying...")
        page_content = await page.content()
        logger.debug(f"Page content: {page_content[:1000]}")  # Log first 1000 characters for inspection
        raise Exception("No post elements found")
    logger.info(f"Found {len(elements)} post elements")
    return elements

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

async def extract_post_urls(page, num_posts):
    post_urls = set()
    scroll_attempts = 0
    max_scroll_attempts = 10

    while scroll_attempts < max_scroll_attempts:
        try:
            elements = await page.query_selector_all('a[href^="/explore/"]')
            logger.info(f"Found {len(elements)} post elements")
            new_urls = {await element.get_attribute('href') for element in elements}
            post_urls.update(new_urls)

            if len(post_urls) >= num_posts:
                logger.info(f"Found required number of posts: {len(post_urls)}")
                break

            previous_height = await page.evaluate('document.body.scrollHeight')
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(2000)
            new_height = await page.evaluate('document.body.scrollHeight')

            if new_height == previous_height:
                logger.info("Reached end of page or no new content loaded")
                break
            
            logger.info(f"Scrolled. New height: {new_height}")
        except PlaywrightError as e:
            logger.warning(f"Error during scrolling: {e}")
            await page.wait_for_timeout(2000)  # Wait a bit before retrying

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

async def extract_post_info(page):
    post_info = {}
    selectors = {
        'title': '#detail-title',
        'description': 'span[data-v-6b50f68a]',
        'date': 'span.date',
        'author': '#noteContainer > div.interaction-container > div.author-container > div > div.info > a.name > span'
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

async def scrape_post(page, post_url, keyword_folder):
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
        post_folder = os.path.join(keyword_folder, post_folder_name)
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


async def scrape_xhs_search(keyword, num_posts):
    logger.info(f"Starting scrape for keyword: {keyword}")
    search_url = XHS_SEARCH_URL.format(keyword)

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
            await load_page(page, search_url)
            
            await page.wait_for_load_state('networkidle', timeout=30000)
            await page.wait_for_timeout(5000)  # Wait an additional 5 seconds

            # Check if we're still on a search results page
            if not page.url.startswith("https://www.xiaohongshu.com/search_result"):
                logger.warning(f"Page navigated to unexpected URL: {page.url}")
                raise Exception("Navigation to non-search page")
            
            logger.info(f"Settled on search URL: {page.url}")

            # Wait for post elements with retry mechanism
            elements = await wait_for_posts(page)

            post_urls = await extract_post_urls(page, num_posts)

            # Create keyword folder
            keyword_folder = os.path.join('/Users/yz/Desktop/spider/xhs_search', sanitize_filename(keyword))
            os.makedirs(keyword_folder, exist_ok=True)

            post_count = 0
            for post_url in post_urls:
                if post_count >= num_posts:
                    break
                if not await scrape_post(page, post_url, keyword_folder):
                    logger.warning(f"Failed to scrape post {post_url}")
                await asyncio.sleep(random.uniform(2, 5))
                post_count += 1

        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
        finally:
            await browser.close()
            logger.info("Browser closed")

async def main():
    keyword = input("Enter the search keyword: ")
    num_posts = int(input("Enter the number of posts to download (default is 20): ") or 20)
    await scrape_xhs_search(keyword, num_posts)
    print("Scraping completed. Check the Desktop for the output files.")

if __name__ == "__main__":
    asyncio.run(main())