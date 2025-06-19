import requests
import socket
import csv
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed

# === CONFIGURATION ===
CONFIG_FILE = 'config.yaml'

CLOUDFLARE_API_BASE = 'https://api.cloudflare.com/client/v4'

def load_config(config_file):
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    return config

def get_dns_records(zone_id, headers):
    url = f'{CLOUDFLARE_API_BASE}/zones/{zone_id}/dns_records'
    records = []
    page = 1
    per_page = 100

    while True:
        params = {
            'page': page,
            'per_page': per_page
        }
        resp = requests.get(url, headers=headers, params=params)
        data = resp.json()
        if not data.get('success'):
            raise Exception(f"API error for zone {zone_id}: {data}")

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

def test_origin(zone_name, record, headers):
    proxied = record.get('proxied', False)
    r_type = record.get('type')
    content = record.get('content')
    name = record.get('name')

    if not proxied or r_type not in ['CNAME', 'A', 'AAAA']:
        return None  # Skip non-proxied or irrelevant records

    print(f"Testing origin for {zone_name}: {name} ({r_type} -> {content}) ...")

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
        message = 'Origin responded directly - possible DTO'
    else:
        message = 'Origin did not respond directly - not vulnerable'

    return {
        'zone': zone_name,
        'record': name,
        'type': r_type,
        'origin': content,
        'resolved_ip': ip,
        'status': status_code or 'No response',
        'message': message
    }

def export_results_csv(results, filename):
    fieldnames = ['zone', 'record', 'type', 'origin', 'resolved_ip', 'status', 'message']
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            if r:
                writer.writerow(r)
    print(f"✅ Results exported to {filename}")

def process_zone(zone_id, headers, threads):
    try:
        zone_info = requests.get(f'{CLOUDFLARE_API_BASE}/zones/{zone_id}', headers=headers).json()
        zone_name = zone_info['result']['name']
        print(f"Processing zone: {zone_name} ({zone_id})")

        records = get_dns_records(zone_id, headers)

        results = []
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(test_origin, zone_name, r, headers) for r in records]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    print(f"{result['zone']} | {result['record']} -> {result['origin']} | {result['status']} | {result['message']}")
                    results.append(result)
        return results

    except Exception as e:
        print(f"Error processing zone {zone_id}: {e}")
        return []

def main():
    config = load_config(CONFIG_FILE)
    api_token = config.get('api_token')
    zone_ids = config.get('zones', [])
    threads = config.get('threads', 10)
    output_csv = config.get('output_csv', 'dto_check_results.csv')

    headers = {
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json'
    }

    print(f"Loaded config: {len(zone_ids)} zones, {threads} threads, output: {output_csv}")

    all_results = []

    with ThreadPoolExecutor(max_workers=len(zone_ids)) as executor:
        futures = [executor.submit(process_zone, zid, headers, threads) for zid in zone_ids]
        for future in as_completed(futures):
            zone_results = future.result()
            all_results.extend(zone_results)

    export_results_csv(all_results, output_csv)

if __name__ == '__main__':
    main()
