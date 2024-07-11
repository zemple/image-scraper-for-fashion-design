import os
import asyncio
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from urllib.parse import urljoin
import random
import time

# Dictionary of websites and their search URL formats
WEBSITES = {
    "alamour" : "https://www.alamourthelabel.com/en-us/search?q={}",
    "vogue" : "https://www.vogue.com/search?q={}&sort=score+desc",
    "pinterest" : "https://www.pinterest.com/search/pins/?q={}&rs=typed",
    "ins_profile" : "https://www.picuki.com/profile/{}",
    "ins_tag" : "https://www.picuki.com/tag/{}"
}

def download_image(session, url, folder_path, count, filename):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': url
        }
        response = session.get(url, headers=headers, stream=True, timeout=10)
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '').lower()
            if 'image' in content_type and content_type not in ['image/svg+xml', 'image/gif']:
                file_path = os.path.join(folder_path, filename)
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(8192):
                        f.write(chunk)
                print(f"Downloaded: {url} as {filename}")
                return count + 1
            else:
                print(f"Skipped: {url} (Not a valid image, or is SVG/GIF)")
        else:
            print(f"Failed to download: {url} - Status code: {response.status_code}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")
    return count

def create_folder(keyword):
    folder_path = os.path.join(os.path.expanduser('~'), 'Desktop', f'{keyword}_images')
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"Created new directory: {folder_path}")
    else:
        print(f"Using existing directory: {folder_path}")
    return folder_path

def extract_alamour_images(soup, keyword):
    product_containers = soup.find_all('li', class_='productgrid--item')
    img_data = []
    
    for container in product_containers:
        product_name = container.find('h2', class_='productitem--title')
        if product_name and keyword.lower() in product_name.text.lower():
            for img_class in ['productitem--image-primary', 'productitem--image-alternate']:
                img = container.find('img', class_=img_class)
                if img:
                    srcset = img.get('srcset', '')
                    if srcset:
                        # Get the highest resolution image from srcset
                        sources = srcset.split(',')
                        highest_res = sources[-1].strip().split(' ')[0]
                        img_data.append((highest_res, product_name.text.strip()))
                    elif img.get('src'):
                        img_data.append((img['src'], product_name.text.strip()))
    
    return img_data

def extract_ins_images(soup):
    img_data = []
    post_images = soup.find_all('img', class_='post-image')
    for img in post_images:
        src = img.get('src')
        alt = img.get('alt', 'No description')
        if src:
            img_data.append((src, alt))
    return img_data

async def scrape_images(website, keyword, num_images=20):
    folder_path = create_folder(keyword)
    session = requests.Session()
    count = 0

    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # Set to True for headless mode
        context = await browser.new_context(user_agent=random.choice(user_agents))
        page = await context.new_page()

        try:
            url = WEBSITES[website].format(keyword)
            print(f"Navigating to {url}")
            
            await page.goto(url, timeout=60000, wait_until="networkidle")
            
            # Random delay
            await page.wait_for_timeout(random.randint(3000, 6000))
            
            print("Page loaded successfully")
            print(f"Current page title: {await page.title()}")
            print(f"Current URL: {page.url}")

            # Scroll to load all content
            last_height = await page.evaluate("document.body.scrollHeight")
            for _ in range(5):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(random.randint(1000, 3000))
                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            print("Extracting image URLs")
            page_content = await page.content()
            soup = BeautifulSoup(page_content, 'html.parser')

            if website == "alamour":
                img_data = extract_alamour_images(soup, keyword)
                img_urls = [urljoin(url, img_url) for img_url, _ in img_data]
            elif website in ["ins_profile", "ins_tag"]:
                img_data = extract_ins_images(soup)
                img_urls = [img_url for img_url, _ in img_data]
            else:
                img_tags = soup.find_all('img')
                img_urls = []
                for img in img_tags:
                    src = img.get('src') or img.get('data-src')
                    if src and not src.lower().endswith('.svg'):
                        img_urls.append(urljoin(url, src))
            
                srcset = img.get('srcset')
                if srcset:
                    sources = srcset.split(',')
                    highest_res = sources[-1].strip().split(' ')[0]
                    if not highest_res.lower().endswith('.svg'):
                        img_urls.append(urljoin(url, highest_res))

            # Remove duplicates while preserving order
            img_urls = list(dict.fromkeys(img_urls))

            print(f"Found {len(img_urls)} unique image URLs")

            for index, img_url in enumerate(img_urls):
                if count >= num_images:
                    break
                if website in ["alamour", "ins"]:
                    description = img_data[index][1]
                    safe_description = "".join([c if c.isalnum() else "_" for c in description])[:50]  # Limit length and replace non-alphanumeric characters
                    filename = f"{safe_description}_{index + 1}.jpg"
                else:
                    filename = f"image_{count + 1}.jpg"
                count = download_image(session, img_url, folder_path, count, filename)
            if count == 0:
                print("No images were downloaded. The page source is:")
                print(await page.content())

        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            await browser.close()

    print(f"Download completed. Total images downloaded: {count}")

async def main():
    print("Available websites:", ", ".join(WEBSITES.keys()))
    website = input("Enter the website name: ").lower()
    if website not in WEBSITES:
        print("Invalid website name. Please choose from the available options.")
        return
    keyword = input("Enter the search keyword: ")
    num_images = int(input("Enter the number of images to download (default is 20): ") or 20)
    await scrape_images(website, keyword, num_images)

if __name__ == '__main__':
    asyncio.run(main())