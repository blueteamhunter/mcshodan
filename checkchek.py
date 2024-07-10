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
    return response.json()

# Function to audit a specific repository
def audit_repository(repo):
    audit_log = []
    pr_cursor = None
    while True:
        pr_data = get_pull_requests(repo, pr_cursor)
        pull_requests = pr_data['data']['repository']['pullRequests']['nodes']
        pr_page_info = pr_data['data']['repository']['pullRequests']['pageInfo']
        
        for pr in pull_requests:
            for file in pr['files']['nodes']:
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
        
        if not pr_page_info['hasNextPage']:
            break
        pr_cursor = pr_page_info['endCursor']
    
    with open(AUDIT_LOG, 'w') as log_file:
        json.dump(audit_log, log_file, indent=4)

if __name__ == '__main__':
    audit_repository(REPO_NAME)
    print(f'Audit completed for {REPO_NAME}. Check {AUDIT_LOG} for details.')
