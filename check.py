import requests

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

def is_ip_public(ip):
    import ipaddress
    try:
        ip_obj = ipaddress.ip_address(ip)
        return not (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local)
    except ValueError:
        return False

def analyze_records(records):
    vulnerable = []

    for record in records:
        proxied = record.get('proxied', False)
        r_type = record.get('type')
        content = record.get('content')
        name = record.get('name')

        if r_type in ['A', 'AAAA']:
            if not proxied and is_ip_public(content):
                vulnerable.append({
                    'name': name,
                    'type': r_type,
                    'content': content,
                    'reason': 'Unproxied public IP'
                })
        
        elif r_type == 'CNAME':
            if not proxied:
                vulnerable.append({
                    'name': name,
                    'type': r_type,
                    'content': content,
                    'reason': 'Unproxied CNAME (check if origin)'
                })

    return vulnerable

def main():
    print("Fetching DNS records...")
    records = get_dns_records(ZONE_ID)
    print(f"Found {len(records)} records.")

    print("Analyzing records for DTO vulnerability...")
    vulnerable_records = analyze_records(records)

    if not vulnerable_records:
        print("✅ No DTO vulnerabilities detected — all records proxied or safe!")
    else:
        print("⚠️ Potential DTO vulnerable records:")
        for v in vulnerable_records:
            print(f" - {v['name']} ({v['type']} -> {v['content']}): {v['reason']}")

if __name__ == '__main__':
    main()
