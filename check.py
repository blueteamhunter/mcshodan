import requests
import json
import os

# Configuration
GITHUB_TOKEN = 'your_github_token'
ORG_NAME = 'your_organization_name'
REPO_NAME = 'your_test_repository'  # Specify the repository name for testing
AUDIT_LOG = '/tmp/audit_log_test.txt'  # Use an absolute path to avoid any relative path issues

headers = {
    'Authorization': f'Bearer {GITHUB_TOKEN}',
    'Content-Type': 'application/json'
}

# GraphQL query to get PRs and changes in .checkmarx directory
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
    url = 'https://api.github.com/graphql'
    try:
        response = requests.post(url, headers=headers, json={'query': query, 'variables': variables})
        print(f'Requesting URL: {url}')
        print(f'Status Code: {response.status_code}')
        if response.status_code == 200:
            return response.json()
        else:
            print(f'Error: {response.status_code} - {response.text}')
            return None
    except requests.exceptions.RequestException as e:
        print(f'Request failed: {e}')
        return None

# Function to audit changes to files in .checkmarx directory in a repository
def audit_repository(repo):
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
            for file in pr.get('files', {}).get('nodes', []):
                if file['path'].startswith('.checkmarx/'):
                    try:
                        with open(AUDIT_LOG, 'a') as log_file:
                            log_file.write(f'Repository: {repo}\n')
                            log_file.write(f'Pull Request: {pr["number"]} - {pr["title"]}\n')
                            log_file.write(f'Author: {pr["author"]["login"]}\n')
                            log_file.write(f'Date: {pr["createdAt"]}\n')
                            log_file.write(f'File: {file["path"]} (Additions: {file["additions"]}, Deletions: {file["deletions"]})\n')
                            log_file.write('\n')
                    except Exception as e:
                        print(f"Failed to write to log file {AUDIT_LOG}: {e}")
        
        if not pr_page_info.get('hasNextPage'):
            break
        pr_cursor = pr_page_info.get('endCursor')

# Main execution
if __name__ == '__main__':
    if os.path.exists(AUDIT_LOG):
        os.remove(AUDIT_LOG)
        print(f"Existing audit log {AUDIT_LOG} removed.")
    
    # Audit the specified repository
    audit_repository(REPO_NAME)
    
    if os.path.exists(AUDIT_LOG):
        print(f'Audit completed for {REPO_NAME}. Check {AUDIT_LOG} for details.')
    else:
        print(f"Audit log {AUDIT_LOG} was not created.")
