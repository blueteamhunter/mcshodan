import requests
import pandas as pd

# Function to check if a domain is behind a WAF
def check_waf(domain):
    try:
        response = requests.get(f'http://{domain}', timeout=10)
        headers = response.headers

        # List of common WAF headers and their values
        waf_headers = {
            'Cloudflare': 'cf-ray',
            'AWS WAF': 'x-amz-cf-id',
            'Incapsula': 'incap_ses',
            'Akamai': 'akamai',
            'Sucuri': 'x-sucuri-id',
            'F5 BIG-IP': 'bigipserver',
            'Barracuda': 'bneddosvg'
        }

        for waf, header in waf_headers.items():
            if any(header in key.lower() for key in headers):
                return f'{domain} is behind {waf} WAF'

        return f'{domain} is not behind a known WAF'

    except requests.RequestException as e:
        return f'Error checking {domain}: {str(e)}'

# Read the CSV file
df = pd.read_csv('domains.csv')

# Check each domain
results = df['domain name'].apply(check_waf)

# Print the results
for result in results:
    print(result)
