import requests
import json

# Configuration
GITHUB_TOKEN = 'your_generated_github_token'
ORG_NAME = 'your_organization_name'
REPO_NAME = 'your_test_repository'  # Static repository name for testing
AUDIT_LOG = 'audit_log_test.json'

headers = {
    'Authorization': f'Bearer {GITHUB_TOKEN}',
    'Content-Type': 'application/json'
}

# GraphQL query to get PRs
def get_pull_requests(repo, after_cursor=None):
    query = '''
    query($owner: String!, $repo: String!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequests(first: 100, after: $cursor) {
          nodes {
            number
            title
            createdAt
            author {
              login
            }
            files(first: 100) {
              nodes {
                path
                additions
                deletions
              }
            }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    '''
    variables = {'owner': ORG_NAME, 'repo': repo, 'cursor': after_cursor}
    response = requests.post('https://api.github.com/graphql', headers=headers, json={'query': query, 'variables': variables})
    
    if response.status_code != 200:
        print(f'Error {response.status_code}: {response.text}')
        return None
    
    response_json = response.json()
    if 'errors' in response_json:
        print(f'GraphQL errors: {response_json["errors"]}')
        return None
    
    return response_json

# Function to audit a specific repository
def audit_repository(repo):
    audit_log = []
    pr_cursor = None
    while True:
        pr_data = get_pull_requests(repo, pr_cursor)
        if pr_data is None:
            print('Failed to retrieve pull request data.')
            break
        
        repository = pr_data.get('data', {}).get('repository', {})
        if not repository:
            print('No repository data found in response.')
            break
        
        pull_requests = repository.get('pullRequests', {}).get('nodes', [])
        pr_page_info = repository.get('pullRequests', {}).get('pageInfo', {})
        
        for pr in pull_requests:
            print(f'Checking PR #{pr["number"]}: {pr["title"]}')
            for file in pr.get('files', {}).get('nodes', []):
                print(f'  - Found file: {file["path"]}')
                if file['path'].startswith('.checkmarx/') and file['path'].endswith('application.yml'):
                    audit_log.append({
                        'repository': repo,
                        'pull_request': pr['number'],
                        'title': pr['title'],
                        'created_at': pr['createdAt'],
                        'author': pr['author']['login'],
                        'file': file['path'],
                        'additions': file['additions'],
                        'deletions': file['deletions']
                    })
        
        if not pr_page_info.get('hasNextPage'):
            break
        pr_cursor = pr_page_info.get('endCursor')
    
    if not audit_log:
        print('No matching pull requests found.')
    else:
        with open(AUDIT_LOG, 'w') as log_file:
            json.dump(audit_log, log_file, indent=4)
        print(f'Audit log written to {AUDIT_LOG}')

if __name__ == '__main__':
    try:
        audit_repository(REPO_NAME)
        print(f'Audit completed for {REPO_NAME}.')
    except Exception as e:
        print(f'An error occurred: {e}')
