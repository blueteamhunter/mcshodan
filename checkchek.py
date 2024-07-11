import requests

# Configuration
GITHUB_TOKEN = 'your_github_token'
ORG_NAME = 'your_organization_name'
REPOS = []  # List to hold repository names

headers = {
    'Authorization': f'Bearer {GITHUB_TOKEN}',
    'Content-Type': 'application/json'
}

# GraphQL query to get repositories
def get_repositories(after_cursor=None):
    query = '''
    query($org: String!, $cursor: String) {
      organization(login: $org) {
        repositories(first: 100, after: $cursor) {
          nodes {
            name
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    '''
    variables = {'org': ORG_NAME, 'cursor': after_cursor}
    response = requests.post('https://api.github.com/graphql', headers=headers, json={'query': query, 'variables': variables})
    if response.status_code == 200:
        return response.json()
    else:
        print(f'Error: {response.status_code} - {response.text}')
        return None

# Main execution to fetch and print all repository names
if __name__ == '__main__':
    after_cursor = None
    while True:
        repo_data = get_repositories(after_cursor)
        if repo_data is None:
            print('Failed to retrieve repository data.')
            break
        
        repositories = repo_data.get('data', {}).get('organization', {}).get('repositories', {}).get('nodes', [])
        page_info = repo_data.get('data', {}).get('organization', {}).get('repositories', {}).get('pageInfo', {})
        
        for repo in repositories:
            REPOS.append(repo['name'])
        
        if not page_info.get('hasNextPage'):
            break
        after_cursor = page_info.get('endCursor')
    
    print(f"Found {len(REPOS)} repositories: {REPOS}")
