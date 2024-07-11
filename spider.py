import os
import time
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

def download_image(url, folder_path, count):
    try:
        response = requests.get(url, stream=True, timeout=10)
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '').lower()
            if 'image' in content_type and 'gif' not in content_type:
                extension = content_type.split('/')[-1]
                filename = os.path.join(folder_path, f"image_{count}.{extension}")
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(8192):
                        f.write(chunk)
                print(f"Downloaded: {url}")
                return count + 1
            else:
                print(f"Skipped: {url} (Not a valid image or is a GIF)")
        else:
            print(f"Failed to download: {url}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")
    return count

def find_search_input(driver):
    selectors = [
        (By.CSS_SELECTOR, "input[type='search']"),
        (By.CSS_SELECTOR, "input[name='search']"),
        (By.CSS_SELECTOR, "input[placeholder*='search' i]"),
        (By.CSS_SELECTOR, "input[aria-label*='search' i]"),
        (By.CSS_SELECTOR, "input[class*='search' i]"),
        (By.XPATH, "//input[contains(@placeholder, 'search') or contains(@aria-label, 'search')]"),
        (By.XPATH, "//input[@type='text' and (@placeholder or @aria-label)]")
    ]
    
    for by, selector in selectors:
        try:
            return WebDriverWait(driver, 10).until(EC.element_to_be_clickable((by, selector)))
        except TimeoutException:
            continue
    
    return None

def wait_for_page_load(driver, timeout=30):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        return True
    except TimeoutException:
        return False

def perform_search(driver, keyword):
    search_input = find_search_input(driver)
    if search_input:
        initial_url = driver.current_url
        search_input.clear()
        search_input.send_keys(keyword)
        search_input.send_keys(Keys.RETURN)
        
        # Wait for URL to change or page content to update
        try:
            WebDriverWait(driver, 30).until(lambda d: d.current_url != initial_url or keyword.lower() in d.page_source.lower())
            print(f"Search for '{keyword}' appears to have been successful.")
            return True
        except TimeoutException:
            print(f"Could not confirm if search for '{keyword}' was successful.")
            return False
    else:
        print("Could not find a search input. Proceeding with current page content.")
        return False

def create_folder(keyword):
    folder_path = os.path.join(os.path.expanduser('~'), 'Desktop', f'{keyword}_images')
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"Created new directory: {folder_path}")
    else:
        print(f"Using existing directory: {folder_path}")
    return folder_path

def scrape_images(url, keyword, num_images=20):
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=service, options=options)
    
    count = 0
    folder_path = create_folder(keyword)

    try:
        print(f"Navigating to {url}")
        driver.get(url)
        initial_url = driver.current_url
        
        if perform_search(driver, keyword):
            print(f"Search performed. URL changed from {initial_url} to {driver.current_url}")
        else:
            print("Search may not have been performed successfully. Proceeding with current page content.")

        print(f"Current page title: {driver.title}")
        print(f"Current URL: {driver.current_url}")

        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        while count < num_images and scroll_attempts < 5:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0
            last_height = new_height

            print("Extracting image URLs")
            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            img_tags = soup.find_all('img')
            img_urls = [img.get('src') for img in img_tags if img.get('src') and img.get('src').startswith('http')]

            print(f"Found {len(img_urls)} image URLs")

            for img_url in img_urls:
                if count >= num_images:
                    break
                count = download_image(img_url, folder_path, count)

        if count == 0:
            print("No images were downloaded. The page source is:")
            print(driver.page_source)

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        driver.quit()

    print(f"Download completed. Total images downloaded: {count}")

def main():
    url = input("Enter the URL of the website's search page: ")
    keyword = input("Enter the search keyword: ")
    num_images = int(input("Enter the number of images to download (default is 20): ") or 20)
    scrape_images(url, keyword, num_images)

if __name__ == '__main__':
    main()