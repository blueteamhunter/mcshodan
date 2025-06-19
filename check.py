import requests
import socket
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed

# === CONFIGURATION ===
API_TOKEN = 'YOUR_CLOUDFLARE_API_TOKEN'
ZONE_ID = 'YOUR_CLOUDFLARE_ZONE_ID'
THREADS = 10
OUTPUT_CSV = 'dto_check_results.csv'

CLOUDFLARE_API_BASE = 'https://api.cloudflare.com/client/v4'

HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type': 'application/json'
}

def get_dns_records(zone_id):
    url = f'{CLOUDFLARE_API_BASE}/zones/{zone_id}/dns_records'
    records = []
    page = 1
    per_page = 100

    while True:
        params = {
            'page': page,
            'per_page': per_page
        }
        resp = requests.get(url, headers=HEADERS, params=params)
        data = resp.json()
        if not data.get('success'):
            raise Exception(f"API error: {data}")

        records.extend(data['result'])

        if page * per_page >= data['result_info']['total_count']:
            break
        page += 1
    
    return records

def try_direct_connection(target, use_https=True):
    try:
        scheme = 'https' if use_https else 'http'
        url = f"{scheme}://{target}"
        resp = requests.get(url, timeout=5)
        return resp.status_code
    except Exception:
        return None

def resolve_cname_target(target):
    try:
        return socket.gethostbyname(target)
    except Exception:
        return None

def test_origin(record):
    proxied = record.get('proxied', False)
    r_type = record.get('type')
    content = record.get('content')
    name = record.get('name')

    if not proxied or r_type not in ['CNAME', 'A', 'AAAA']:
        return None  # Skip non-proxied or irrelevant records

    print(f"Testing origin for {name} ({r_type} -> {content}) ...")

    target = content

    if r_type == 'CNAME':
        ip = resolve_cname_target(content)
    else:
        ip = content

    # Try HTTPS first
    status_code = try_direct_connection(content, use_https=True)
    if not status_code:
        # Try HTTP fallback
        status_code = try_direct_connection(content, use_https=False)

    if status_code:
        message = '⚠️ Origin responded directly — possible DTO'
    else:
        message = '✅ Origin did not respond directly'

    return {
        'record': name,
        'type': r_type,
        'origin': content,
        'resolved_ip': ip,
        'status': status_code or 'No response',
        'message': message
    }

def export_results_csv(results, filename):
    fieldnames = ['record', 'type', 'origin', 'resolved_ip', 'status', 'message']
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            if r:
                writer.writerow(r)
    print(f"✅ Results exported to {filename}")

def main():
    print("Fetching DNS records...")
    records = get_dns_records(ZONE_ID)
    print(f"Found {len(records)} records.")

    print(f"Testing origins for DTO vulnerability using {THREADS} threads...")

    results = []
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(test_origin, r) for r in records]
        for future in as_completed(futures):
            result = future.result()
            if result:
                print(f"{result['record']} -> {result['origin']} | {result['status']} | {result['message']}")
                results.append(result)

    export_results_csv(results, OUTPUT_CSV)

if __name__ == '__main__':
    main()
