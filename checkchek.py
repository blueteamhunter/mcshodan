import requests

# Configuration
GITHUB_TOKEN = 'your_github_token'
ORG_NAME = 'your_organization_name'
REPOS = []  # List to hold repository names

headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

# Function to get all repositories in the organization
def get_repositories():
    global REPOS
    url = f'https://api.github.com/orgs/{ORG_NAME}/repos?per_page=100'
    while url:
        response = requests.get(url, headers=headers)
        print(f"Requesting URL: {url}")
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            repos = response.json()
            for repo in repos:
                REPOS.append(repo['name'])
            # Check if there's another page of results
            if 'next' in response.links:
                url = response.links['next']['url']
            else:
                url = None
        else:
            print(f'Failed to fetch repositories: {response.status_code} - {response.text}')
            break

if __name__ == '__main__':
    get_repositories()
    print(f"Found {len(REPOS)} repositories: {REPOS}")
