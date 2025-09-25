from flask import Flask, render_template, request, jsonify
import requests
import re
from bs4 import BeautifulSoup
import json
import threading

app = Flask(__name__)

# --- Global Değişkenler ---
LUNAPROXY_AUTH_TOKEN = "iwh1prycyjl07yn62car8eeepkoxtupuknatq5r28ogub32yp75paalu48ar64hy"
BASE_URL = "https://www.akakce.com"
HEPSIBURADA_SELLER_CODE = "1195915"

CATEGORIES = {
    "Anakart": "anakart.html",
    "Bilgisayar Kasası": "bilgisayar-kasasi.html",
    "Ekran Kartı": "ekran-karti.html",
    "Harddisk": "harddisk.html",
    "SSD": "ssd.html",
    "Soğutma Sistemi": "sogutma-sistemi.html",
    "Ses Kartı": "ses-karti.html",
    "RAM": "ram.html",
    "Power Supply": "power-supply.html",
    "İşlemci": "islemci.html",
    "All in One PC": "all-in-one-pc.html",
    "Laptop / Notebook": "laptop-notebook.html",
    "Masaüstü Bilgisayar": "bilgisayar-masaustu.html",
    "Mini PC": "mini-pc.html",
    "Oyun Bilgisayarı": "oyun-bilgisayari.html",
    "Tablet": "tablet.html",
    "Hoparlör": "hoparlor.html",
    "Klavye": "klavye.html",
    "Mouse": "mouse.html",
    "Kulaklık": "kulaklik.html",
    "Oyuncu Koltuğu": "oyuncu-koltugu.html",
    "Access Point": "access-point.html",
    "Modem": "modem.html",
    "WiFi Güçlendirici": "wifi-guclendirici.html",
    "Router": "router.html",
    "Monitör": "monitor.html",
}

# Arka plan işlemi ve sonuçlar için global değişkenler
scraping_thread = None
products_data = []
stop_scraping_flag = threading.Event()
scraping_status = "idle" # idle, running, stopped
scraping_progress = 0

# --- Yardımcı Fonksiyonlar ---
def get_html_with_proxy(url):
    """Fetches HTML content from a URL using LunaProxy."""
    if stop_scraping_flag.is_set():
        return None
    proxy_url = "https://unlocker-api.lunaproxy.com/request"
    headers = {
        "Authorization": f"Bearer {LUNAPROXY_AUTH_TOKEN}",
        "content-type": "application/json"
    }
    payload = {"url": url, "type": "html", "country": "tr", "js_render": "True"}
    try:
        response = requests.post(proxy_url, headers=headers, data=json.dumps(payload), timeout=60)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def parse_price(price_str):
    """Converts a price string like '3.999,00 TL' to a float."""
    try:
        return float(price_str.replace('.', '').replace(',', '.').split(' ')[0])
    except (ValueError, IndexError):
        return 0.0

def scrape_products_task(category_path, discount_rate, page_limit):
    """Scrapes product information in a background thread."""
    global products_data, scraping_status, scraping_progress
    
    products_data = []
    scraping_status = "running"
    scraping_progress = 0
    
    category_base_url = f"{BASE_URL}/{category_path}/{HEPSIBURADA_SELLER_CODE}"
    
    first_page_html = get_html_with_proxy(category_base_url)
    if not first_page_html:
        scraping_status = "idle"
        return

    soup = BeautifulSoup(first_page_html, 'html.parser')
    last_page_link = soup.select_one('a[title="Son sayfaya git"]')
    total_pages = 1
    if last_page_link and last_page_link.get('href'):
        # Regex to extract page number from URLs like /monitor,17.html/1195915
        match = re.search(r',(\d+)\.html', last_page_link['href'])
        if match:
            total_pages = int(match.group(1))
    
    if page_limit == -1:
        pages_to_scan = total_pages
    else:
        pages_to_scan = min(total_pages, page_limit)
    print(f"Toplam {total_pages} sayfa bulundu. Taranacak sayfa: {pages_to_scan if page_limit != -1 else 'Tümü'}")

    for page in range(1, pages_to_scan + 1):
        if stop_scraping_flag.is_set():
            print("Tarama durduruldu.")
            break
        
        scraping_progress = int((page / pages_to_scan) * 100)
        
        # Construct page URL, e.g., https://www.akakce.com/monitor,2.html/1195915
        page_url = f"{BASE_URL}/{category_path.replace('.html', '')},{page}.html/{HEPSIBURADA_SELLER_CODE}"
        print(f"Taranan sayfa: {page_url} ({scraping_progress}%)")
        
        html = get_html_with_proxy(page_url)
        if not html:
            continue

        soup = BeautifulSoup(html, 'html.parser')
        products = soup.find_all('li', attrs={'data-pr': True})

        for product in products:
            if stop_scraping_flag.is_set():
                break

            title_element = product.find('h3', class_='pn_v8')
            link_element = product.find('a', class_='pw_v8')
            if not title_element or not link_element:
                continue
            
            title = title_element.text.strip()
            href = link_element['href']
            product_url = BASE_URL + href if href.startswith('/') else href

            price_elements = product.select('.p_w_v9 .pt_v8')
            prices = [parse_price(p.text) for p in price_elements if p.text.strip()]

            if len(prices) >= 2:
                hepsiburada_price = prices[0]
                competitor_price = prices[1]
                
                if hepsiburada_price * (1 + discount_rate / 100) <= competitor_price:
                    price_diff_percent = ((competitor_price - hepsiburada_price) / hepsiburada_price) * 100
                    products_data.append({
                        'title': title,
                        'url': product_url,
                        'hepsiburada_price': hepsiburada_price,
                        'competitor_price': competitor_price,
                        'diff_percent': round(price_diff_percent)
                    })
    
    if stop_scraping_flag.is_set():
        scraping_status = "stopped"
    else:
        scraping_status = "idle"
        scraping_progress = 100
    print("Tarama tamamlandı.")

# --- Flask Rotaları ---
@app.route('/')
def index():
    return render_template('index.html', categories=CATEGORIES)

@app.route('/scrape', methods=['POST'])
def start_scraping():
    global scraping_thread
    if scraping_thread and scraping_thread.is_alive():
        return jsonify({'status': 'error', 'message': 'Tarama zaten devam ediyor.'}), 400

    discount_rate = request.form.get('discount', 10, type=int)
    page_limit = request.form.get('page_limit', 5, type=int)
    category_path = request.form.get('category')

    if not category_path:
        return jsonify({'status': 'error', 'message': 'Kategori seçimi zorunludur.'}), 400

    stop_scraping_flag.clear()
    
    scraping_thread = threading.Thread(target=scrape_products_task, args=(category_path, discount_rate, page_limit))
    scraping_thread.start()
    
    return jsonify({'status': 'success', 'message': 'Tarama başlatıldı.'})

@app.route('/stop', methods=['POST'])
def stop_scraping():
    global scraping_thread
    if not scraping_thread or not scraping_thread.is_alive():
        return jsonify({'status': 'error', 'message': 'Çalışan bir tarama işlemi yok.'}), 400
        
    stop_scraping_flag.set()
    return jsonify({'status': 'success', 'message': 'Tarama durduruluyor...'})

@app.route('/results')
def get_results():
    return jsonify({'products': products_data})

@app.route('/status')
def get_status():
    return jsonify({'status': scraping_status, 'progress': scraping_progress})

if __name__ == '__main__':
    app.run(debug=True, port=5001)

