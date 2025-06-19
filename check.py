import requests
import socket

# === CONFIGURATION ===
API_TOKEN = 'YOUR_CLOUDFLARE_API_TOKEN'
ZONE_ID = 'YOUR_CLOUDFLARE_ZONE_ID'

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
    except Exception as e:
        return None

def resolve_cname_target(target):
    try:
        return socket.gethostbyname(target)
    except Exception:
        return None

def analyze_records(records):
    results = []

    for record in records:
        proxied = record.get('proxied', False)
        r_type = record.get('type')
        content = record.get('content')
        name = record.get('name')

        # Only check if it's proxied (meaning origin hidden via Cloudflare)
        if proxied and r_type in ['CNAME', 'A', 'AAAA']:
            print(f"Testing origin for {name} ({r_type} -> {content}) ...")

            target = content

            if r_type == 'CNAME':
                ip = resolve_cname_target(content)
                print(f" - Resolved {content} to {ip}")
            else:
                ip = content

            # Try HTTPS first
            status_code = try_direct_connection(content, use_https=True)
            if not status_code:
                # Try HTTP fallback
                status_code = try_direct_connection(content, use_https=False)

            if status_code:
                results.append({
                    'record': name,
                    'origin': content,
                    'resolved_ip': ip,
                    'status': status_code,
                    'message': '⚠️ Origin responded directly — possible DTO'
                })
            else:
                results.append({
                    'record': name,
                    'origin': content,
                    'resolved_ip': ip,
                    'status': 'No response',
                    'message': '✅ Origin did not respond directly'
                })
    
    return results

def main():
    print("Fetching DNS records...")
    records = get_dns_records(ZONE_ID)
    print(f"Found {len(records)} records.")

    print("Testing origins for DTO vulnerability...")
    results = analyze_records(records)

    for r in results:
        print(f"{r['record']} -> {r['origin']} ({r['resolved_ip']}) | {r['status']} | {r['message']}")

if __name__ == '__main__':
    main()
